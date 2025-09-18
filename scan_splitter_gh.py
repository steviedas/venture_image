#!/usr/bin/env python3
"""
photo_splitter.py (Python 3)
- Manually split a single image that contains multiple photos into separate files.
- Draw rectangles, click "Go" to save crops alongside the source.
- Set PATH_TO_PROCESS below to a file or a folder; no CLI args required.

Original author: Greg Lavino (2010), modernized for Python 3 and hard-coded path.
"""

import os
from pathlib import Path

# ------------- CONFIG -------------
PATH_TO_PROCESS = r"C:\Users\stevi\Desktop\scan_split_test"  # file or folder
INCLUDE_SUBDIRS = True                                       # if PATH_TO_PROCESS is a folder
IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".tif", ".tiff", ".bmp")
THUMB_SIZE = (600, 600)                                      # canvas preview size
# ----------------------------------

from PIL import Image, ImageTk
import tkinter as Tkinter

class Rect:
    def __init__(self, *args):
        self.set_points(*args)

    def set_points(self, *args):
        if len(args) == 2:
            pt1, pt2 = args
        elif len(args) == 1:
            pt1 = (0, 0)
            pt2 = args[0]
        else:
            pt1 = (0, 0)
            pt2 = (0, 0)
        x1, y1 = pt1
        x2, y2 = pt2
        self.left   = min(x1, x2)
        self.top    = min(y1, y2)
        self.right  = max(x1, x2)
        self.bottom = max(y1, y2)
        self._update_dims()

    def clip_to(self, containing_rect):
        cr = containing_rect
        self.top    = max(self.top, cr.top)
        self.bottom = min(self.bottom, cr.bottom)
        self.left   = max(self.left, cr.left)
        self.right  = min(self.right, cr.right)
        self._update_dims()

    def _update_dims(self):
        self.w = self.right - self.left
        self.h = self.bottom - self.top

    def scale_rect(self, scale):
        x_scale, y_scale = scale
        r = Rect()
        r.top = int(self.top * y_scale)
        r.bottom = int(self.bottom * y_scale)
        r.right = int(self.right * x_scale)
        r.left = int(self.left * x_scale)
        r._update_dims()
        return r

    def __repr__(self):
        return f"({self.left},{self.top})-({self.right},{self.bottom})"


class Application(Tkinter.Frame):
    def __init__(self, master=None, filename=None):
        super().__init__(master)
        self.grid()
        self.create_widgets()
        self.croprect_start = None
        self.croprect_end   = None
        self.canvas_rects   = []
        self.crop_rects     = []
        self.current_rect   = None
        self.filename       = None
        self.image          = None
        self.image_thumb    = None
        self.image_rect     = None
        self.image_thumb_rect = None
        self.scale          = (1.0, 1.0)

        if filename:
            self.filename = filename
            self.load_image()

    def create_widgets(self):
        self.canvas = Tkinter.Canvas(self, height=1, width=1, relief=Tkinter.SUNKEN)
        self.canvas.bind("<Button-1>", self.canvas_mouse1_down)
        self.canvas.bind("<ButtonRelease-1>", self.canvas_mouse1_up)
        self.canvas.bind("<B1-Motion>", self.canvas_mouse1_drag)

        self.goButton    = Tkinter.Button(self, text="Go",    command=self.start_cropping)
        self.resetButton = Tkinter.Button(self, text="Reset", command=self.reset)
        self.undoButton  = Tkinter.Button(self, text="Undo",  command=self.undo_last)
        self.quitButton  = Tkinter.Button(self, text="Quit",  command=self.quit)

        self.canvas.grid(row=0, columnspan=4)
        self.goButton.grid(row=1, column=0)
        self.resetButton.grid(row=1, column=1)
        self.undoButton.grid(row=1, column=2)
        self.quitButton.grid(row=1, column=3)

    # ---- mouse handlers ----
    def canvas_mouse1_down(self, event):
        self.croprect_start = (event.x, event.y)

    def canvas_mouse1_drag(self, event):
        if not self.croprect_start:
            return
        if self.current_rect:
            self.canvas.delete(self.current_rect)
        x1, y1 = self.croprect_start
        x2, y2 = event.x, event.y
        self.current_rect = self.canvas.create_rectangle((x1, y1, x2, y2))

    def canvas_mouse1_up(self, event):
        if not self.croprect_start:
            return
        self.croprect_end = (event.x, event.y)
        self.set_crop_area()
        if self.current_rect:
            self.canvas.delete(self.current_rect)
            self.current_rect = None
        self.croprect_start = None

    # ---- crop selection management ----
    def set_crop_area(self):
        r = Rect(self.croprect_start, self.croprect_end)
        r.clip_to(self.image_thumb_rect)
        if min(r.h, r.w) < 10:  # ignore tiny boxes
            return
        self.drawrect(r)
        self.crop_rects.append(r.scale_rect(self.scale))

    def undo_last(self):
        if self.canvas_rects:
            cr = self.canvas_rects.pop()
            self.canvas.delete(cr)
        if self.crop_rects:
            self.crop_rects.pop()

    def drawrect(self, rect):
        bbox = (rect.left, rect.top, rect.right, rect.bottom)
        cr = self.canvas.create_rectangle(bbox, activefill="", fill="red", stipple="gray25")
        self.canvas_rects.append(cr)

    # ---- image I/O ----
    def display_image(self):
        self.photoimage = ImageTk.PhotoImage(self.image_thumb)
        w, h = self.image_thumb.size
        self.canvas.configure(width=w, height=h)
        self.canvas.create_image(0, 0, anchor=Tkinter.NW, image=self.photoimage)

    def reset(self):
        self.canvas.delete(Tkinter.ALL)
        self.canvas_rects = []
        self.crop_rects = []
        if self.image_thumb:
            self.display_image()

    def load_image(self):
        self.image = Image.open(self.filename)
        print(f"Loaded: {self.filename} size={self.image.size}")
        self.image_rect = Rect(self.image.size)

        self.image_thumb = self.image.copy()
        self.image_thumb.thumbnail(THUMB_SIZE)
        self.image_thumb_rect = Rect(self.image_thumb.size)

        self.display_image()
        x_scale = float(self.image_rect.w) / max(1, self.image_thumb_rect.w)
        y_scale = float(self.image_rect.h) / max(1, self.image_thumb_rect.h)
        self.scale = (x_scale, y_scale)

    def newfilename(self, filenum):
        f, e = os.path.splitext(self.filename)
        return f"{f}__crop__{filenum}{e}"

    def start_cropping(self):
        if not self.crop_rects:
            print("No crop rectangles drawn.")
        else:
            for idx, croparea in enumerate(self.crop_rects, start=1):
                outpath = self.newfilename(idx)
                self.crop(croparea, outpath)
                print(f"Saved: {outpath}  from {croparea}")
        # close this window; outer loop (main) will move to the next file
        self.master.destroy()

    def crop(self, croparea, filename):
        ca = (croparea.left, croparea.top, croparea.right, croparea.bottom)
        newimg = self.image.crop(ca)
        newimg.save(filename)


# --------- runner helpers ---------
def iter_image_files(target: Path, include_subdirs: bool) -> list[Path]:
    if target.is_file():
        return [target]
    files = []
    if include_subdirs:
        for p in target.rglob("*"):
            if p.is_file() and p.suffix.lower() in IMAGE_EXTS:
                files.append(p)
    else:
        for p in target.iterdir():
            if p.is_file() and p.suffix.lower() in IMAGE_EXTS:
                files.append(p)
    return sorted(files)

def main():
    target = Path(PATH_TO_PROCESS).expanduser().resolve()
    if not target.exists():
        print(f"ERROR: PATH_TO_PROCESS does not exist: {target}")
        return

    file_list = iter_image_files(target, INCLUDE_SUBDIRS)
    if not file_list:
        print(f"No images found under: {target}")
        return

    print(f"Processing {len(file_list)} image(s) from: {target}")
    for filepath in file_list:
        root = Tkinter.Tk()
        root.title("Photo Splitter — " + os.path.basename(filepath))
        app = Application(master=root, filename=str(filepath))
        app.mainloop()   # returns when user clicks Go or closes
        # root.destroy() already called in start_cropping via master.destroy()

if __name__ == "__main__":
    main()
