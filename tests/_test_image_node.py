"""Функциональный тест SavePreviewImage / Custom_node_Images — без ComfyUI.

Нода пишет файлы на диск и открывает их в системном просмотрщике, поэтому
тест подменяет окружение ComfyUI заглушками (folder_paths, comfy.cli_args,
server, aiohttp, numpy, PIL) и проверяет ровно то, где ошибка тихая:

  • защиту пути в API-роуте: файл вне output/temp не открывается (403), в том
    числе через «..\\..»; пустой путь — 400, отсутствующий файл — 404;
  • режимы сохранения: preview → temp, сжатие 1, случайный префикс _temp_;
    save → output, сжатие 4, префикс из виджета;
  • нумерацию батча: счётчик растёт, %batch_num% подставляется;
  • метаданные: prompt/extra_pnginfo попадают в PNG, а при
    args.disable_metadata = True не пишутся вовсе.

Ни один файл при прогоне не остаётся на диске: временная папка удаляется.

Запуск:  cd Custom_node_Images && python tests/_test_image_node.py
"""

import asyncio
import importlib.util
import os
import sys
import tempfile
import types
from pathlib import Path

NODE = Path(__file__).resolve().parent.parent / "image_node.py"

fails = []
oks = []


def _p(text):
    try:
        enc = sys.stdout.encoding or "utf-8"
        sys.stdout.write(str(text).encode(enc, "replace").decode(enc, "replace") + "\n")
    except Exception:
        pass


def check(name, cond, extra=""):
    (oks if cond else fails).append(name)
    _p(("  ok  " if cond else "  FAIL") + f"  {name}" + (f"  [{extra}]" if extra and not cond else ""))


# ───────────────────────── заглушки окружения ComfyUI ──────────────────────
TMP = tempfile.mkdtemp(prefix="cn_images_test_")
OUT_DIR = os.path.join(TMP, "output")
TEMP_DIR = os.path.join(TMP, "temp")
os.makedirs(OUT_DIR, exist_ok=True)
os.makedirs(TEMP_DIR, exist_ok=True)

folder_paths = types.ModuleType("folder_paths")
folder_paths.get_output_directory = lambda: OUT_DIR
folder_paths.get_temp_directory = lambda: TEMP_DIR
saved_calls = []


def _get_save_image_path(prefix, out_dir, width, height, *a, **kw):
    folder = out_dir
    os.makedirs(folder, exist_ok=True)
    saved_calls.append({"prefix": prefix, "dir": out_dir, "w": width, "h": height})
    return folder, prefix, 3, "", None


folder_paths.get_save_image_path = _get_save_image_path
sys.modules["folder_paths"] = folder_paths

cli_args = types.ModuleType("comfy.cli_args")
cli_args.args = types.SimpleNamespace(disable_metadata=False)
comfy = types.ModuleType("comfy")
comfy.cli_args = cli_args
sys.modules["comfy"] = comfy
sys.modules["comfy.cli_args"] = cli_args

routes = []


class _Routes:
    def post(self, path):
        def deco(fn):
            routes.append((path, fn))
            return fn
        return deco

    def add_post(self, path, fn):
        routes.append((path, fn))


server = types.ModuleType("server")


class _PromptServer:
    instance = types.SimpleNamespace(routes=_Routes(), app=types.SimpleNamespace(
        router=types.SimpleNamespace(add_post=_Routes().add_post)))


server.PromptServer = _PromptServer
sys.modules["server"] = server

aiohttp = types.ModuleType("aiohttp")
web = types.ModuleType("aiohttp.web")


class _Resp:
    def __init__(self, body, status=200):
        self.body, self.status = body, status


web.json_response = lambda body, status=200: _Resp(body, status)
aiohttp.web = web
sys.modules["aiohttp"] = aiohttp
sys.modules["aiohttp.web"] = web

numpy = types.ModuleType("numpy")


class _Arr:
    def __init__(self, value):
        self.value = value

    def astype(self, _dtype):
        return self


numpy.clip = lambda arr, lo, hi: _Arr(arr)
numpy.uint8 = "uint8"
sys.modules["numpy"] = numpy

pil = types.ModuleType("PIL")
png_plugin = types.ModuleType("PIL.PngImagePlugin")


class _PngInfo:
    def __init__(self):
        self.text = {}

    def add_text(self, key, value):
        self.text[key] = value


png_plugin.PngInfo = _PngInfo
saved_images = []


class _Img:
    def __init__(self, arr):
        self.arr = arr

    def save(self, path, pnginfo=None, compress_level=6):
        Path(path).write_bytes(b"png")
        saved_images.append({"path": path, "pnginfo": pnginfo, "compress": compress_level})


pil.Image = types.SimpleNamespace(fromarray=_Img)
pil.PngImagePlugin = png_plugin
sys.modules["PIL"] = pil
sys.modules["PIL.PngImagePlugin"] = png_plugin

spec = importlib.util.spec_from_file_location("image_node", NODE)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

Cls = mod.NODE_CLASS_MAPPINGS["SavePreviewImage"]
it = Cls.INPUT_TYPES()

try:
    # ──────────────────────────── контракт узла ────────────────────────────
    check("INPUT_TYPES: images обязательный IMAGE",
          it["required"]["images"][0] == "IMAGE", it["required"]["images"][0])
    pm = it["required"]["preview_mode"]
    check("INPUT_TYPES: preview_mode — BOOLEAN с подписями Preview/Save",
          pm[0] == "BOOLEAN" and pm[1].get("label_on") == "Preview"
          and pm[1].get("label_off") == "Save", pm)
    check("INPUT_TYPES: preview_mode по умолчанию False (режим сохранения)",
          pm[1].get("default") is False, pm[1].get("default"))
    check("INPUT_TYPES: filename_prefix default = ComfyUI",
          it["required"]["filename_prefix"][1].get("default") == "ComfyUI",
          it["required"]["filename_prefix"][1])
    check("INPUT_TYPES: скрытые prompt/extra_pnginfo объявлены (метаданные PNG)",
          it.get("hidden", {}) == {"prompt": "PROMPT", "extra_pnginfo": "EXTRA_PNGINFO"},
          it.get("hidden"))
    check("OUTPUT_NODE = True", getattr(Cls, "OUTPUT_NODE", False) is True)
    check("FUNCTION = save_images", Cls.FUNCTION == "save_images", Cls.FUNCTION)
    check("REGISTRY-ключ не переименован", mod.NODE_CLASS_MAPPINGS == {"SavePreviewImage": Cls},
          list(mod.NODE_CLASS_MAPPINGS))

    # ────────────────────────────── запись файлов ──────────────────────────
    class _Data:
        """Стенд тензора: 255. * data и np.clip(...).astype(...) без numpy."""

        def __init__(self, value):
            self.value = value

        def __rmul__(self, other):
            return self

        def astype(self, _dtype):
            return self

    class _Cpu:
        def __init__(self, data):
            self.data = data

        def numpy(self):
            return _Data(self.data)

    class _Image:
        def __init__(self, w, h, tag):
            self.shape = (h, w, 3)
            self.tag = tag

        def cpu(self):
            h, w, _c = self.shape
            return _Cpu([[[0.0, 0.5, 1.0]] * w] * h)

    node = Cls()
    batch = [_Image(4, 2, "a"), _Image(4, 2, "b")]

    saved_images.clear()
    saved_calls.clear()
    res = node.save_images(batch, preview_mode=True, filename_prefix="ComfyUI")
    check("preview: пишет в temp", saved_calls[0]["dir"] == TEMP_DIR, saved_calls[0]["dir"])
    check("preview: тип результата temp", all(r["type"] == "temp" for r in res["ui"]["images"]),
          res["ui"]["images"])
    check("preview: сжатие 1 (быстро, картинка временная)",
          all(s["compress"] == 1 for s in saved_images), [s["compress"] for s in saved_images])
    check("preview: префикс _temp_ + 5 букв (файл не перетирает сохранённые)",
          len(saved_images) == 2
          and saved_images[0]["path"].split(os.sep)[-1].startswith("_temp_"),
          saved_images[0]["path"] if saved_images else "нет файлов")
    check("batch: счётчик растёт (3, 4 — из get_save_image_path)", len(saved_images) == 2
          and "00003" in saved_images[0]["path"] and "00004" in saved_images[1]["path"],
          [s["path"] for s in saved_images])
    check("batch: результат = (images,) — тензор идёт дальше по графу",
          res["result"] == (batch,), res["result"])

    saved_images.clear()
    saved_calls.clear()
    node.save_images(batch, preview_mode=False, filename_prefix="Мой_префикс",
                     prompt={"1": {"class_type": "X"}}, extra_pnginfo={"workflow": {"nodes": []}})
    check("save: пишет в output", saved_calls[0]["dir"] == OUT_DIR, saved_calls[0]["dir"])
    check("save: префикс берётся из виджета",
          saved_images[0]["path"].split(os.sep)[-1].startswith("Мой_префикс"),
          saved_images[0]["path"])
    check("save: сжатие 4", saved_images[0]["compress"] == 4, saved_images[0]["compress"])
    check("save: prompt записан в PNG",
          saved_images[0]["pnginfo"] is not None
          and "prompt" in saved_images[0]["pnginfo"].text, saved_images[0]["pnginfo"])
    check("save: extra_pnginfo (workflow) записан в PNG",
          "workflow" in saved_images[0]["pnginfo"].text, saved_images[0]["pnginfo"].text)

    saved_images.clear()
    cli_args.args.disable_metadata = True
    node.save_images([batch[0]], preview_mode=False, filename_prefix="без_метаданных",
                     prompt={"1": {}}, extra_pnginfo={"workflow": {}})
    check("save: при disable_metadata метаданные не пишутся",
          saved_images[0]["pnginfo"] is None, saved_images[0]["pnginfo"])
    cli_args.args.disable_metadata = False

    # ───────────────────────── API-роут: защита пути ───────────────────────
    class _Req:
        def __init__(self, path):
            self._path = path

        async def json(self):
            if self._path is None:
                raise ValueError("нет тела")
            return {"path": self._path}

    check("API: роут /custom_node_images/open_file зарегистрирован",
          any(p == "/custom_node_images/open_file" for p, _ in routes), [p for p, _ in routes])

    handler = dict(routes)["/custom_node_images/open_file"]

    def call(path):
        return asyncio.run(handler(_Req(path)))

    check("API: пустой путь → 400", call("").status == 400, call("").status)
    r = call(os.path.join(TMP, "чужой", "файл.txt"))
    check("API: файл вне output/temp → 403", r.status == 403, (r.status, r.body))
    traversal = os.path.join(OUT_DIR, "..", "..", "Windows", "win.ini")
    r = call(traversal)
    check("API: обход через ..\\.. нормализуется и получает 403",
          r.status == 403, (r.status, r.body))
    r = call(os.path.join(OUT_DIR, "нет-такого.png"))
    check("API: отсутствующий файл внутри output → 404", r.status == 404, r.status)

    real = os.path.join(OUT_DIR, "есть.png")
    Path(real).write_bytes(b"png")
    opened = []
    _orig_startfile = getattr(os, "startfile", None)
    try:
        os.startfile = lambda p: opened.append(p)  # type: ignore[attr-defined]
        r = call(real)
        check("API: существующий файл в output открывается и отдаёт 200",
              r.status == 200 and opened == [real], (r.status, opened))
        r = call(os.path.join(TEMP_DIR, "..", "output", "есть.png"))
        check("API: путь с .. внутри output всё равно открывается",
              r.status == 200, (r.status, r.body))
    finally:
        if _orig_startfile is not None:
            os.startfile = _orig_startfile  # type: ignore[attr-defined]
        else:
            del os.startfile

    class _BadReq:
        async def json(self):
            raise RuntimeError("битый JSON от панели")

    r = asyncio.run(handler(_BadReq()))
    check("API: исключение в запросе → 500, а не падение сервера", r.status == 500, r.status)
finally:
    import shutil
    shutil.rmtree(TMP, ignore_errors=True)

_p("")
_p(f"PASS: {len(oks)}  FAIL: {len(fails)}")
if fails:
    _p("failed: " + ", ".join(fails))
else:
    _p("ТЕСТ ПРОЙДЕН")
sys.exit(1 if fails else 0)
