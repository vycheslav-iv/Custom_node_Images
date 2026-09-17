import os
import json
import random
import numpy as np
from PIL import Image
from PIL.PngImagePlugin import PngInfo
import folder_paths
from comfy.cli_args import args
from aiohttp import web
from server import PromptServer


# ── API: open file in Windows default viewer ──
# Define handler first, then register routes
async def open_image_file(request):
    try:
        data = await request.json()
        filepath = data.get("path", "")
        if not filepath:
            return web.json_response({"error": "No path"}, status=400)
        filepath = os.path.normpath(filepath)
        out_dir = os.path.normpath(folder_paths.get_output_directory())
        tmp_dir = os.path.normpath(folder_paths.get_temp_directory())
        if not (filepath.startswith(out_dir) or filepath.startswith(tmp_dir)):
            return web.json_response({"error": "Access denied"}, status=403)
        if not os.path.isfile(filepath):
            return web.json_response({"error": "Not found"}, status=404)
        os.startfile(filepath)
        return web.json_response({"status": "ok"})
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)

# Register route with fallback
try:
    PromptServer.instance.routes.post("/custom_node_images/open_file")(open_image_file)
except Exception:
    try:
        PromptServer.instance.app.router.add_post("/custom_node_images/open_file", open_image_file)
    except Exception:
        pass


class SavePreviewImage:
    """
    Combined Save Image / Preview Image node.
    - preview_mode = True  -> saves to temp (preview behavior)
    - preview_mode = False -> saves to output (save behavior)
    """

    def __init__(self):
        self.output_dir = folder_paths.get_output_directory()
        self.temp_dir = folder_paths.get_temp_directory()
        self.type = "output"
        self.compress_level = 4

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "images": ("IMAGE", {"tooltip": "The images to save or preview."}),
                "preview_mode": ("BOOLEAN", {
                    "default": False,
                    "label_on": "Preview",
                    "label_off": "Save",
                    "tooltip": "Preview mode (temp) or Save mode (output with prefix)."
                }),
                "filename_prefix": ("STRING", {
                    "default": "ComfyUI",
                    "tooltip": "Prefix for the file (only used when preview_mode is OFF)."
                }),
            },
            "hidden": {
                "prompt": "PROMPT",
                "extra_pnginfo": "EXTRA_PNGINFO"
            },
        }

    RETURN_TYPES = ("IMAGE",)
    RETURN_NAMES = ("images",)
    FUNCTION = "save_images"
    OUTPUT_NODE = True
    CATEGORY = "My_custom_nodes/Image"
    DESCRIPTION = "Save images to output folder or preview them in-browser. Click the button to open in Windows viewer."

    def save_images(self, images, preview_mode=True, filename_prefix="ComfyUI", prompt=None, extra_pnginfo=None):
        if preview_mode:
            output_dir = self.temp_dir
            self.type = "temp"
            prefix_append = "_temp_" + ''.join(random.choice("abcdefghijklmnopqrstuvwxyz") for x in range(5))
            full_prefix = prefix_append
            compress_level = 1
        else:
            output_dir = self.output_dir
            self.type = "output"
            full_prefix = filename_prefix
            compress_level = self.compress_level

        full_output_folder, filename, counter, subfolder, _ = folder_paths.get_save_image_path(
            full_prefix, output_dir, images[0].shape[1], images[0].shape[0]
        )

        results = list()
        for batch_number, image in enumerate(images):
            i = 255. * image.cpu().numpy()
            img = Image.fromarray(np.clip(i, 0, 255).astype(np.uint8))
            metadata = None
            if not args.disable_metadata:
                metadata = PngInfo()
                if prompt is not None:
                    metadata.add_text("prompt", json.dumps(prompt))
                if extra_pnginfo is not None:
                    for x in extra_pnginfo:
                        metadata.add_text(x, json.dumps(extra_pnginfo[x]))
            filename_with_batch_num = filename.replace("%batch_num%", str(batch_number))
            file = f"{filename_with_batch_num}_{counter:05}_.png"
            full_path = os.path.join(full_output_folder, file)
            img.save(full_path, pnginfo=metadata, compress_level=compress_level)
            results.append({
                "filename": file,
                "subfolder": subfolder,
                "type": self.type,
                "full_path": full_path
            })
            counter += 1

        return {"ui": {"images": results}, "result": (images,)}


NODE_CLASS_MAPPINGS = {
    "SavePreviewImage": SavePreviewImage,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "SavePreviewImage": "Image Save/Preview",
}
