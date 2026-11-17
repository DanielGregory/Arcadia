// Shimmering water, applied to the backdrop layer (sky and sea).
// Only pixels inside sea_mask move: a slow ripple bends the picture a little,
// and bright patches (the sun's path) sparkle.
shader_type canvas_item;

uniform sampler2D sea_mask : filter_linear;
uniform float ripple = 0.0022;     // how far the ripple bends the image (fraction of the width)
uniform float speed = 0.5;
uniform float sparkle = 0.55;

void fragment() {
	float m = texture(sea_mask, UV).r;
	vec2 uv = UV;
	// Two crossing waves: long horizontal swells and finer vertical shimmer.
	uv.x += sin(UV.y * 260.0 + TIME * speed * 3.0) * cos(UV.x * 37.0 + TIME * speed) * ripple * m;
	uv.y += cos(UV.x * 120.0 + TIME * speed * 2.0) * ripple * 0.4 * m;
	vec4 c = texture(TEXTURE, uv);
	float lum = dot(c.rgb, vec3(0.299, 0.587, 0.114));
	float glint = pow(max(0.0, sin(UV.x * 900.0 + TIME * 4.0) * sin(UV.y * 650.0 - TIME * 3.0)), 24.0);
	c.rgb += glint * m * smoothstep(0.55, 0.9, lum) * sparkle;
	COLOR = c;
}
