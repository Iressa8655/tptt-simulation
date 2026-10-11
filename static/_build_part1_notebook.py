"""產生並執行 V2_part1_attachment_sweep.ipynb，第一部分止點掃描。

⭐ 每一格都是三明治：📖 故事、程式（每行註解）、👀 結果解讀。
⭐ 程式在這裡跑一次，輸出（文字和圖）一起寫進 notebook。
⭐ 解讀格的數字要等第一次跑完才寫，所以 READ 字典可以先留空。

用法
    python _build_part1_notebook.py
"""

import base64
import contextlib
import io
import json
import os
import sys
import uuid

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

sys.stdout.reconfigure(encoding="utf-8")

ROOT = os.path.dirname(os.path.abspath(__file__))
NOTEBOOK = os.path.join(ROOT, "V2_part1_attachment_sweep.ipynb")
VAULT_ATTACH = (r"C:\Users\User\Dropbox\Iressa's note\Projects\Opensim MSK"
                r"\attachments")

from _part1_cells import CELLS, READ  # noqa: E402


def markdown(text):
    """一個 markdown 格子。"""
    return {"cell_type": "markdown", "id": uuid.uuid4().hex[:8],
            "metadata": {}, "source": text.strip("\n").splitlines(keepends=True)}


def run_code(source, scope):
    """跑一格程式，收下印出的文字和圖。"""
    images = []

    def capture_show(*args, **kwargs):
        figure = plt.gcf()
        buffer = io.BytesIO()
        figure.savefig(buffer, format="png", dpi=100, bbox_inches="tight")
        images.append((base64.b64encode(buffer.getvalue()).decode("ascii"),
                       figure.get_size_inches()))
        plt.close("all")

    plt.show = capture_show
    printed = io.StringIO()
    with contextlib.redirect_stdout(printed):
        exec(source, scope)
    outputs = []
    if printed.getvalue():
        outputs.append({"name": "stdout", "output_type": "stream",
                        "text": printed.getvalue().splitlines(keepends=True)})
    for image, size in images:
        outputs.append({
            "output_type": "display_data", "metadata": {},
            "data": {"image/png": image,
                     "text/plain": [f"<Figure size {size[0]*100:.0f}x"
                                    f"{size[1]*100:.0f}>"]},
        })
    cell = {"cell_type": "code", "id": uuid.uuid4().hex[:8], "metadata": {},
            "execution_count": None, "outputs": outputs,
            "source": source.strip("\n").splitlines(keepends=True)}
    return cell, printed.getvalue()


def main():
    cells = []
    scope = {"__name__": "__main__"}
    for kind, key, text in CELLS:
        if kind == "md":
            cells.append(markdown(text))
        elif kind == "read":
            cells.append(markdown(READ.get(key) or f"### 👀 {key}. 待填"))
        else:
            print(f"--- running {key}", file=sys.stderr)
            cell, printed = run_code(text, scope)
            cells.append(cell)
            print(f"===== {key} =====")
            print(printed)

    notebook = {
        "cells": cells,
        "metadata": {
            "kernelspec": {"display_name": "opensim_scripting",
                           "language": "python", "name": "python3"},
            "language_info": {"name": "python", "version": "3.12.10"},
        },
        "nbformat": 4, "nbformat_minor": 5,
    }
    with open(NOTEBOOK, "w", encoding="utf-8") as handle:
        json.dump(notebook, handle, ensure_ascii=False, indent=1)
        handle.write("\n")

    # 圖複製一份到 Obsidian
    for name in os.listdir(os.path.join(ROOT, "figures")):
        if name.startswith("v2-p1-") and name.endswith(".png"):
            with open(os.path.join(ROOT, "figures", name), "rb") as source, \
                    open(os.path.join(VAULT_ATTACH, name), "wb") as target:
                target.write(source.read())
    print("notebook cells:", len(cells))


if __name__ == "__main__":
    main()
