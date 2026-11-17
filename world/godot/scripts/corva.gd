extends Node2D
## Corva as a living painting.
##
## The canonical painting, split into depth layers by render/make_layers.py, is
## stacked back to front. A slow "camera" drift (plus the pointer or a finger)
## moves each layer by a different amount, so nearer things slide past farther
## ones: that is parallax, and it makes the flat painting feel deep. On top:
## shimmering water (shaders/water.gdshader), a breathing glow on the sun, and a
## day cycle that tints the whole scene from golden hour through night.
##
## This node only DISPLAYS. It never decides anything about the world.

const ART := "res://art/corva/"

@export var drift_px := 34.0         ## how far the camera wanders, in painting pixels (keep under the 48 px layer band / 0.6)
@export var drift_period := 45.0     ## seconds for one slow drift loop
@export var day_length := 240.0      ## seconds for a full day in the demo; 0 = follow the viewer's real clock
@export var pan_period := 70.0       ## portrait screens: seconds to pan across the painting and back

var info: Dictionary
var layers: Array[Sprite2D] = []
var parallax: Array[float] = []
var painting := Node2D.new()         # holds every layer; scaled to cover the screen
var tint := CanvasModulate.new()     # the day cycle colours everything below it
var sun_glow := Sprite2D.new()
var pointer := Vector2.ZERO          # -1..1 from the mouse or a finger, eased
var pointer_target := Vector2.ZERO
var t := 0.0
var base := Vector2.ZERO             # painting position that centres it
var pan_room := 0.0                  # extra width available to pan on tall screens

# Day cycle: phase 0..1 -> tint. 0.25 is the painting as painted (golden hour).
var day := Gradient.new()


func _ready() -> void:
	info = JSON.parse_string(FileAccess.get_file_as_string(ART + "layers.json"))
	add_child(tint)
	add_child(painting)

	for l in info["layers"]:
		var s := Sprite2D.new()
		s.texture = load(ART + l["file"])
		s.centered = false
		painting.add_child(s)
		layers.append(s)
		parallax.append(float(l["parallax"]))
		if l["index"] == 0:
			_add_sun_glow()  # the glow sits just in front of the sky, behind the mountains

	# Water shimmer on the backdrop (sky + sea) layer only.
	var water := ShaderMaterial.new()
	water.shader = load("res://shaders/water.gdshader")
	water.set_shader_parameter("sea_mask", load(ART + "sea_mask.png"))
	layers[0].material = water

	day.offsets = PackedFloat32Array([0.0, 0.12, 0.25, 0.45, 0.62, 0.75, 0.88, 1.0])
	day.colors = PackedColorArray([
		Color(0.30, 0.34, 0.52),  # deep night
		Color(0.95, 0.72, 0.68),  # dawn
		Color(1.00, 1.00, 1.00),  # golden hour (the painting as painted)
		Color(1.06, 1.04, 1.02),  # bright day
		Color(1.00, 0.90, 0.80),  # late afternoon
		Color(0.92, 0.68, 0.62),  # dusk
		Color(0.40, 0.42, 0.60),  # night falls
		Color(0.30, 0.34, 0.52),  # deep night
	])

	get_viewport().size_changed.connect(_fit)
	_fit()


func _add_sun_glow() -> void:
	var g := GradientTexture2D.new()
	g.fill = GradientTexture2D.FILL_RADIAL
	g.fill_from = Vector2(0.5, 0.5)
	g.fill_to = Vector2(1.0, 0.5)
	g.width = 256
	g.height = 256
	var grad := Gradient.new()
	grad.colors = PackedColorArray([Color(1.0, 0.92, 0.7, 0.35), Color(1.0, 0.8, 0.5, 0.0)])
	g.gradient = grad
	sun_glow.texture = g
	var add := CanvasItemMaterial.new()
	add.blend_mode = CanvasItemMaterial.BLEND_MODE_ADD
	sun_glow.material = add
	sun_glow.position = Vector2(info["sun"][0], info["sun"][1])
	painting.add_child(sun_glow)


## Scale the painting to cover the whole screen, leaving room for the drift.
func _fit() -> void:
	var screen := get_viewport_rect().size
	var img := Vector2(info["size"][0], info["size"][1])
	var margin := drift_px * 1.3
	var s: float = max(screen.x / (img.x - 2.0 * margin), screen.y / (img.y - 2.0 * margin))
	painting.scale = Vector2.ONE * s
	base = (screen - img * s) / 2.0
	pan_room = max(0.0, img.x * s - screen.x - 2.0 * margin * s)


func _input(event: InputEvent) -> void:
	if event is InputEventMouseMotion or event is InputEventScreenDrag:
		var screen := get_viewport_rect().size
		pointer_target = (event.position / screen - Vector2(0.5, 0.5)) * 2.0


func _process(delta: float) -> void:
	t += delta
	pointer = pointer.lerp(pointer_target.clamp(Vector2(-1, -1), Vector2(1, 1)), 1.0 - exp(-delta * 2.0))

	# The camera wanders on a slow, never-quite-repeating loop, nudged by the pointer.
	var w := TAU * t / drift_period
	var drift := Vector2(sin(w), 0.6 * sin(w * 0.61 + 1.3)) * drift_px * 0.6 + pointer * drift_px * 0.6
	for i in layers.size():
		layers[i].position = drift * parallax[i]
	sun_glow.position = Vector2(info["sun"][0], info["sun"][1]) + drift * parallax[0]

	# Tall (portrait) screens can't show the whole width: pan slowly across it.
	var pan := 0.0
	if pan_room > 0.0:
		pan = sin(TAU * t / pan_period) * pan_room / 2.0
	painting.position = base + Vector2(pan, 0.0)

	# Day cycle tint and the sun's breathing glow.
	var phase: float
	if day_length > 0.0:
		phase = fmod(0.2 + t / day_length, 1.0)
	else:
		var now := Time.get_time_dict_from_system()
		phase = fmod((now.hour * 3600.0 + now.minute * 60.0 + now.second) / 86400.0 + 0.5, 1.0)
	tint.color = day.sample(phase)
	var sun_up: float = clamp(1.0 - abs(phase - 0.3) / 0.25, 0.0, 1.0)
	var breathe := 1.0 + 0.06 * sin(t * 0.9)
	sun_glow.scale = Vector2.ONE * 0.9 * breathe
	sun_glow.modulate.a = sun_up
