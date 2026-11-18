// The look: render the 3D scene into a texture, then paint it.
//
// 1. Kuwahara filter: for each pixel, look at the four square regions around it and take the
//    average colour of the one that varies least. Edges stay sharp while flat areas break into
//    soft, uniform patches: it looks like brushwork. The radius is the brush size.
// 2. Tone mapping (ACES, as in film) so bright skies roll off softly instead of clipping.
// 3. A warm Claude Lorrain grade: golden highlights, warm brown shadows, a touch more saturation.
// 4. A vignette and a faint canvas grain.
//
// The filter runs at a reduced resolution (quality.renderScale) into a second texture, which is
// then stretched to the screen: that's what keeps it fast on a phone.

import * as THREE from "../../vendor/three.module.min.js";

const quadVS = /* glsl */`varying vec2 vUv; void main() { vUv = uv; gl_Position = vec4(position.xy, 0.0, 1.0); }`;

const paintFS = /* glsl */`
  uniform sampler2D tScene; uniform vec2 texel; uniform int radius; uniform float exposure, time, night;
  varying vec2 vUv;
  vec3 aces(vec3 x) { return clamp((x * (2.51 * x + 0.03)) / (x * (2.43 * x + 0.59) + 0.14), 0.0, 1.0); }
  void main() {
    vec3 col;
    if (radius == 0) {
      col = texture2D(tScene, vUv).rgb;
    } else {
      vec3 m[4]; vec3 s[4];
      for (int k = 0; k < 4; k++) { m[k] = vec3(0.0); s[k] = vec3(0.0); }
      float n = 0.0;
      for (int j = 0; j <= 4; j++) {
        if (j > radius) break;
        for (int i = 0; i <= 4; i++) {
          if (i > radius) break;
          vec3 a = texture2D(tScene, vUv + vec2(-i, -j) * texel).rgb;
          vec3 b = texture2D(tScene, vUv + vec2( i, -j) * texel).rgb;
          vec3 c = texture2D(tScene, vUv + vec2(-i,  j) * texel).rgb;
          vec3 d = texture2D(tScene, vUv + vec2( i,  j) * texel).rgb;
          m[0] += a; s[0] += a * a; m[1] += b; s[1] += b * b;
          m[2] += c; s[2] += c * c; m[3] += d; s[3] += d * d;
          n += 1.0;
        }
      }
      float best = 1e9;
      for (int k = 0; k < 4; k++) {
        vec3 mean = m[k] / n;
        vec3 v = abs(s[k] / n - mean * mean);
        float sigma = v.r + v.g + v.b;
        if (sigma < best) { best = sigma; col = mean; }
      }
    }
    col = aces(col * exposure);
    // warm grade: highlights toward gold, shadows toward warm umber
    float l = dot(col, vec3(0.299, 0.587, 0.114));
    // by day a warm Lorrain grade; at night a cool moonlit one (warm lamps stay warm: they're bright)
    col *= mix(mix(vec3(1.0), vec3(1.07, 1.0, 0.86), 0.65), mix(vec3(0.86, 0.94, 1.12), vec3(1.0), smoothstep(0.35, 0.8, l)), night);
    col += mix(vec3(0.030, 0.018, 0.004), vec3(0.004, 0.010, 0.026), night) * (1.0 - l);
    col = mix(vec3(l), col, 1.10);
    col = clamp(col, 0.0, 1.0);
    // vignette, warm at the edges
    vec2 d = vUv - 0.5;
    float vig = smoothstep(0.85, 0.25, length(d * vec2(1.15, 1.0)));
    col = mix(col * vec3(0.62, 0.52, 0.42), col, vig);
    // canvas grain (fixed, not flickering)
    float grain = fract(sin(dot(floor(vUv / texel), vec2(12.9898, 78.233))) * 43758.5453) - 0.5;
    col += grain * mix(0.026, 0.012, night);
    gl_FragColor = vec4(pow(max(col, 0.0), vec3(1.0 / 2.2)), 1.0);   // to the screen's sRGB
  }`;

const blitFS = /* glsl */`uniform sampler2D tPaint; varying vec2 vUv; void main() { gl_FragColor = texture2D(tPaint, vUv); }`;

export class Painter {
  constructor(renderer, quality) {
    this.renderer = renderer;
    this.quality = quality;
    const opts = { type: THREE.HalfFloatType, samples: quality.shadows ? 4 : 0 };
    this.sceneRT = new THREE.WebGLRenderTarget(1, 1, opts);
    this.paintRT = new THREE.WebGLRenderTarget(1, 1, { type: THREE.UnsignedByteType });
    this.paintRT.texture.minFilter = this.paintRT.texture.magFilter = THREE.LinearFilter;
    this.camera = new THREE.OrthographicCamera(-1, 1, 1, -1, 0, 1);
    this.paintMat = new THREE.ShaderMaterial({
      vertexShader: quadVS, fragmentShader: paintFS, depthTest: false, depthWrite: false,
      uniforms: { tScene: { value: this.sceneRT.texture }, texel: { value: new THREE.Vector2() },
                  radius: { value: quality.kuwahara }, exposure: { value: 1.0 }, time: { value: 0 }, night: { value: 0 } },
    });
    this.blitMat = new THREE.ShaderMaterial({ vertexShader: quadVS, fragmentShader: blitFS, depthTest: false, depthWrite: false,
                                              uniforms: { tPaint: { value: this.paintRT.texture } } });
    this.quad = new THREE.Mesh(new THREE.PlaneGeometry(2, 2), this.paintMat);
    this.quad.frustumCulled = false;
    this.quadScene = new THREE.Scene().add(this.quad);
  }
  setSize(width, height) {
    const pr = this.renderer.getPixelRatio(), s = this.quality.renderScale;
    const w = Math.max(1, Math.round(width * pr * s)), h = Math.max(1, Math.round(height * pr * s));
    this.sceneRT.setSize(w, h);
    this.paintRT.setSize(w, h);
    this.paintMat.uniforms.texel.value.set(1 / w, 1 / h);
  }
  render(scene, camera, exposure, night = 0) {
    const r = this.renderer;
    this.paintMat.uniforms.exposure.value = exposure;
    this.paintMat.uniforms.night.value = night;
    r.setRenderTarget(this.sceneRT);
    r.render(scene, camera);
    this.quad.material = this.paintMat;
    r.setRenderTarget(this.paintRT);
    r.render(this.quadScene, this.camera);
    this.quad.material = this.blitMat;
    r.setRenderTarget(null);
    r.render(this.quadScene, this.camera);
  }
}
