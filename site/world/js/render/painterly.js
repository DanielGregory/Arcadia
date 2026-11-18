// The look: render the 3D scene into a texture (colour + depth), then paint it.
//
// 1. Kuwahara filter: for each pixel, look at the four square regions around it and take the
//    average colour of the one that varies least. Edges stay sharp while flat areas break into
//    soft, uniform patches: it looks like brushwork. The radius is the brush size.
// 2. Aerial perspective: using each pixel's real distance (from the depth buffer), far things fade
//    into the colour of the sky at the horizon, cooling toward violet-blue the further they are.
//    This is what makes painted mountains recede in layers.
// 3. Glow (bloom): bright light (the sun, its path on the sea, windows and lanterns) bleeds softly
//    into its surroundings. Read from blurred, smaller copies of the image (mipmaps): cheap.
// 4. Tone mapping (ACES, as in film), a warm Claude Lorrain grade by day and a cool moonlit one at
//    night, a vignette, and a faint canvas grain.
//
// The filter runs at a reduced resolution (quality.renderScale) into a second texture, which is
// then stretched to the screen: that's what keeps it fast on a phone.

import * as THREE from "../../vendor/three.module.min.js";

const quadVS = /* glsl */`out vec2 vUv; void main() { vUv = uv; gl_Position = vec4(position.xy, 0.0, 1.0); }`;

const paintFS = /* glsl */`
  precision highp float;
  uniform sampler2D tScene, tDepth;
  uniform vec2 texel; uniform int radius;
  uniform float exposure, night, near, far, hazeStart, hazeScale, glow;
  uniform vec3 hazeNear, hazeFar;
  in vec2 vUv; out vec4 outColor;
  vec3 aces(vec3 x) { return clamp((x * (2.51 * x + 0.03)) / (x * (2.43 * x + 0.59) + 0.14), 0.0, 1.0); }
  float viewDist(vec2 uv) {
    float d = texture(tDepth, uv).r;
    float z = d * 2.0 - 1.0;
    return (2.0 * near * far) / (far + near - z * (far - near));
  }
  void main() {
    vec3 col;
    if (radius == 0) {
      col = texture(tScene, vUv).rgb;
    } else {
      vec3 m[4]; vec3 s[4];
      for (int k = 0; k < 4; k++) { m[k] = vec3(0.0); s[k] = vec3(0.0); }
      float n = 0.0;
      for (int j = 0; j <= 4; j++) {
        if (j > radius) break;
        for (int i = 0; i <= 4; i++) {
          if (i > radius) break;
          vec3 a = textureLod(tScene, vUv + vec2(-i, -j) * texel, 0.0).rgb;
          vec3 b = textureLod(tScene, vUv + vec2( i, -j) * texel, 0.0).rgb;
          vec3 c = textureLod(tScene, vUv + vec2(-i,  j) * texel, 0.0).rgb;
          vec3 d = textureLod(tScene, vUv + vec2( i,  j) * texel, 0.0).rgb;
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
    // aerial perspective (the sky itself, at the far plane, is left alone)
    float rawDepth = texture(tDepth, vUv).r;
    if (rawDepth < 0.99999) {
      float dist = viewDist(vUv);
      float h = 1.0 - exp(-pow(max(0.0, dist - hazeStart) * hazeScale, 1.25));
      vec3 haze = mix(hazeNear, hazeFar, smoothstep(300.0, 1600.0, dist));
      col = mix(col, haze, clamp(h, 0.0, 0.92));
    }
    // glow from blurred copies of the bright parts of the image
    vec3 bloom = vec3(0.0);
    bloom += max(textureLod(tScene, vUv, 2.0).rgb - 0.9, 0.0) * 0.35;
    bloom += max(textureLod(tScene, vUv, 4.0).rgb - 0.8, 0.0) * 0.45;
    bloom += max(textureLod(tScene, vUv, 5.5).rgb - 0.75, 0.0) * 0.4;
    col += bloom * glow;

    col = aces(col * exposure);
    float l = dot(col, vec3(0.299, 0.587, 0.114));
    // by day a warm Lorrain grade; at night a cool moonlit one (warm lamps stay warm: they're bright)
    col *= mix(mix(vec3(1.0), vec3(1.07, 1.0, 0.86), 0.65), mix(vec3(0.86, 0.94, 1.12), vec3(1.0), smoothstep(0.35, 0.8, l)), night);
    col += mix(vec3(0.030, 0.018, 0.004), vec3(0.004, 0.010, 0.026), night) * (1.0 - l);
    col = mix(vec3(l), col, 1.10);
    col = clamp(col, 0.0, 1.0);
    vec2 dv = vUv - 0.5;
    float vig = smoothstep(0.85, 0.25, length(dv * vec2(1.15, 1.0)));
    col = mix(col * vec3(0.62, 0.52, 0.42), col, vig);
    float grain = fract(sin(dot(floor(vUv / texel), vec2(12.9898, 78.233))) * 43758.5453) - 0.5;
    col += grain * mix(0.022, 0.012, night);
    outColor = vec4(pow(max(col, 0.0), vec3(1.0 / 2.2)), 1.0);   // to the screen's sRGB
  }`;

const blitFS = /* glsl */`precision highp float; uniform sampler2D tPaint; in vec2 vUv; out vec4 outColor;
  void main() { outColor = texture(tPaint, vUv); }`;

export class Painter {
  constructor(renderer, quality) {
    this.renderer = renderer;
    this.quality = quality;
    // Colour with mipmaps (the glow reads the blurred levels) and a depth texture (the haze).
    this.sceneRT = new THREE.WebGLRenderTarget(1, 1, { type: THREE.HalfFloatType, generateMipmaps: true,
                                                        minFilter: THREE.LinearMipmapLinearFilter, magFilter: THREE.LinearFilter });
    this.sceneRT.depthTexture = new THREE.DepthTexture(1, 1, THREE.UnsignedIntType);
    this.paintRT = new THREE.WebGLRenderTarget(1, 1, { type: THREE.UnsignedByteType });
    this.camera = new THREE.OrthographicCamera(-1, 1, 1, -1, 0, 1);
    this.paintMat = new THREE.ShaderMaterial({
      glslVersion: THREE.GLSL3, vertexShader: quadVS, fragmentShader: paintFS, depthTest: false, depthWrite: false,
      uniforms: {
        tScene: { value: this.sceneRT.texture }, tDepth: { value: this.sceneRT.depthTexture },
        texel: { value: new THREE.Vector2() }, radius: { value: quality.kuwahara },
        exposure: { value: 1 }, night: { value: 0 }, near: { value: 1 }, far: { value: 9000 },
        hazeStart: { value: 220 }, hazeScale: { value: 0.0006 }, glow: { value: quality.glow ?? 1 },
        hazeNear: { value: new THREE.Color() }, hazeFar: { value: new THREE.Color() },
      },
    });
    this.blitMat = new THREE.ShaderMaterial({ glslVersion: THREE.GLSL3, vertexShader: quadVS, fragmentShader: blitFS,
                                              depthTest: false, depthWrite: false, uniforms: { tPaint: { value: this.paintRT.texture } } });
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
  // look: { exposure, night, hazeNear, hazeFar, hazeScale }
  render(scene, camera, look) {
    const r = this.renderer, u = this.paintMat.uniforms;
    u.exposure.value = look.exposure;
    u.night.value = look.night;
    u.hazeNear.value.copy(look.hazeNear);
    u.hazeFar.value.copy(look.hazeFar);
    u.hazeScale.value = look.hazeScale;
    u.near.value = camera.near;
    u.far.value = camera.far;
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
