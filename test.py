WIDTH, HEIGHT = 800, 600

from sdl2 import *
from skia import *
import ctypes
import sys

if SDL_BYTEORDER == SDL_BIG_ENDIAN:
    RED_MASK = 0xFF000000
    GREEN_MASK = 0x00FF0000
    BLUE_MASK = 0x0000FF00
    ALPHA_MASK = 0x000000FF
else:
    RED_MASK = 0x000000FF
    GREEN_MASK = 0x0000FF00
    BLUE_MASK = 0x00FF0000
    ALPHA_MASK = 0xFF000000


def main():
    sdl_window, root_surface, canvas = prepare()

    canvas.clear(ColorWHITE)

    update(sdl_window, root_surface)
    mainloop()


def prepare():
    SDL_Init(SDL_INIT_EVENTS)

    sdl_window = SDL_CreateWindow(
        b"Browser",
        SDL_WINDOWPOS_CENTERED,
        SDL_WINDOWPOS_CENTERED,
        WIDTH,
        HEIGHT,
        SDL_WINDOW_SHOWN,
    )
    root_surface = Surface.MakeRaster(
        ImageInfo.Make(
            WIDTH,
            HEIGHT,
            ct=kRGBA_8888_ColorType,
            at=kUnpremul_AlphaType,
        )
    )

    return sdl_window, root_surface, root_surface.getCanvas()


def update(sdl_window, root_surface):
    skia_image = root_surface.makeImageSnapshot()
    skia_bytes = skia_image.tobytes()

    sdl_surface = SDL_CreateRGBSurfaceFrom(
        skia_bytes,
        WIDTH,
        HEIGHT,
        32,
        4 * WIDTH,
        RED_MASK,
        GREEN_MASK,
        BLUE_MASK,
        ALPHA_MASK,
    )

    rect = SDL_Rect(0, 0, WIDTH, HEIGHT)
    window_surface = SDL_GetWindowSurface(sdl_window)
    SDL_BlitSurface(sdl_surface, rect, window_surface, rect)
    SDL_UpdateWindowSurface(sdl_window)


def mainloop():
    event = SDL_Event()

    while True:
        while SDL_PollEvent(ctypes.byref(event)) != 0:
            if event.type == SDL_QUIT:
                SDL_Quit()
                sys.exit()


def center(window):
    window.update_idletasks()
    w = window.winfo_width()
    h = window.winfo_height()
    scr_w = window.winfo_screenwidth()
    scr_h = window.winfo_screenheight()
    x = (scr_w - w) // 2
    y = (scr_h - h) // 2
    window.geometry(f"+{x}+{y}")


main()
