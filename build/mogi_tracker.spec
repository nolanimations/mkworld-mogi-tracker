import os

root = os.path.abspath(os.path.join(SPECPATH, ".."))

if not os.path.isfile(os.path.join(root, "build", "notices", "THIRD_PARTY_NOTICES.txt")):
    raise SystemExit("build/notices/THIRD_PARTY_NOTICES.txt is missing: run build/build.ps1, which writes it first.")
if not os.path.isfile(os.path.join(root, "mogi_tracker", "model", "rec.bin")):
    raise SystemExit("mogi_tracker/model/rec.bin is missing: run build/build.ps1, which packs the model first.")

a = Analysis(
    [os.path.join(root, "run.py")],
    pathex=[root],
    datas=[
        (os.path.join(root, "mogi_tracker", "web"), "mogi_tracker/web"),
        # the model goes in packed only (build/pack_model.py), never as a plain rec.onnx
        (os.path.join(root, "mogi_tracker", "model", "rec.bin"), "mogi_tracker/model"),
        (os.path.join(root, "mogi_tracker", "model", "dict.txt"), "mogi_tracker/model"),
        (os.path.join(root, "LICENSE"), "."),
        (os.path.join(root, "third_party"), "third_party"),
        (os.path.join(root, "build", "notices", "THIRD_PARTY_NOTICES.txt"), "."),
    ],
    hiddenimports=["pygrabber.dshow_graph", "comtypes.stream"],
    excludes=["tkinter", "matplotlib", "scipy", "pandas", "torch", "paddle", "PySide6", "PyQt5", "PyQt6", "IPython",
              "pytest", "onnx", "sympy", "numba", "sklearn"],
)
UNUSED = ("opencv_videoio_ffmpeg", "_avif")
a.binaries = [b for b in a.binaries if not any(u in b[0] for u in UNUSED)]
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, a.binaries, a.datas, [],
    name="MKWorldMogiTracker",
    icon=os.path.join(root, "build", "icon.ico"),
    console=False,
    upx=False,
)
