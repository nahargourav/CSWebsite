from PIL import Image
import os

# Input & output paths
input_path = "static/images/generated-image (1).png"
output_png = "static/images/favicon.png"
output_ico = "static/images/favicon.ico"

# Zoom factor: 1.0 = no zoom (use full central square), 2.0 = 2x zoom, etc.
zoom = 1.55

# Fraction of the zoomed square height to remove from top+bottom combined.
# e.g. 0.12 => remove ~12% of the zoomed square height (6% top, 6% bottom).
# Increase this to trim more from top and bottom.
vertical_trim_fraction = 0.12

# Open the image
img = Image.open(input_path).convert("RGBA")
w, h = img.size
min_side = min(w, h)

# --- 1) Center crop based on zoom (zoomed square) ---
if zoom <= 1.0:
    crop_size = min_side
else:
    crop_size = int(min_side / zoom)
    if crop_size < 1:
        crop_size = 1

left0 = (w - crop_size) // 2
top0 = (h - crop_size) // 2
right0 = left0 + crop_size
bottom0 = top0 + crop_size

zoomed = img.crop((left0, top0, right0, bottom0))  # size: (crop_size, crop_size)

# --- 2) Trim top & bottom from the zoomed image ---
vf = max(0.0, min(vertical_trim_fraction, 0.49))  # clamp to safe range
trim_pixels_total = int(round(crop_size * vf))
if trim_pixels_total >= crop_size:
    trim_pixels_total = crop_size - 1

top_trim = trim_pixels_total // 2
bottom_trim = trim_pixels_total - top_trim

y0 = top_trim
y1 = crop_size - bottom_trim
if y1 <= y0:
    y1 = y0 + 1

trimmed = zoomed.crop((0, y0, crop_size, y1))  # width=crop_size, height = crop_size - trim_pixels_total
trimmed_w, trimmed_h = trimmed.size

# --- 3) Preserve full width: pad horizontally (not crop) to make the image square ---
# Create a square canvas with side = crop_size, transparent background, and paste trimmed centered vertically.
canvas_side = crop_size
canvas = Image.new("RGBA", (canvas_side, canvas_side), (0, 0, 0, 0))
paste_x = 0  # keep full width; paste at left 0 so no horizontal crop
paste_y = (canvas_side - trimmed_h) // 2
canvas.paste(trimmed, (paste_x, paste_y))

final_img = canvas  # square image

# Safety: ensure at least 1x1
if final_img.size[0] < 1 or final_img.size[1] < 1:
    final_img = final_img.resize((1, 1))

# --- 4) Resize and save as PNG + multi-size ICO ---
favicon_png = final_img.resize((256, 256), Image.LANCZOS)
os.makedirs(os.path.dirname(output_png), exist_ok=True)
favicon_png.save(output_png, format="PNG")

# Save ICO with multiple sizes
sizes = [(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]
favicon_png.save(output_ico, format="ICO", sizes=sizes)

print("Favicon saved as favicon.png and favicon.ico")
