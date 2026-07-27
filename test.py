WIDTH, HEIGHT = 800, 600

from sdl2 import *
from skia import *
import OpenGL.GL
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


sdl_window = None
root_surface = None
canvas = None
skia_context = None
gl_context = None


def main():
    global sdl_window, root_surface, canvas, gl_context, skia_context
    sdl_window, root_surface, canvas, gl_context, skia_context = prepare()

    canvas.clear(ColorWHITE)

    rect = Rect(100, 100, 300, 300)
    rrect = RRect.MakeRectXY(rect, 20, 20)
    canvas.drawRRect(rrect, Paint(Color=Color(255, 0, 0)))

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
        SDL_WINDOW_SHOWN | SDL_WINDOW_OPENGL,
    )

    SDL_GL_SetAttribute(SDL_GL_CONTEXT_MAJOR_VERSION, 3)
    SDL_GL_SetAttribute(SDL_GL_CONTEXT_MINOR_VERSION, 2)
    SDL_GL_SetAttribute(SDL_GL_CONTEXT_FORWARD_COMPATIBLE_FLAG, True)
    SDL_GL_SetAttribute(SDL_GL_CONTEXT_PROFILE_MASK, SDL_GL_CONTEXT_PROFILE_CORE)

    gl_context = SDL_GL_CreateContext(sdl_window)
    print(
        f"** OpenGL initialized: vendor={OpenGL.GL.glGetString(OpenGL.GL.GL_VENDOR)}, render={OpenGL.GL.glGetString(OpenGL.GL.GL_RENDERER)} **"
    )
    print()

    skia_context = GrDirectContext.MakeGL()

    root_surface = Surface.MakeFromBackendRenderTarget(
        skia_context,
        GrBackendRenderTarget(WIDTH, HEIGHT, 0, 0, GrGLFramebufferInfo(0, OpenGL.GL.GL_RGBA8)),
        kBottomLeft_GrSurfaceOrigin,
        kRGBA_8888_ColorType,
        ColorSpace.MakeSRGB(),
    )

    return sdl_window, root_surface, root_surface.getCanvas(), gl_context, skia_context


def update(sdl_window, root_surface):
    root_surface.flushAndSubmit()
    SDL_GL_SwapWindow(sdl_window)


def mainloop():
    global sdl_window, skia_context, gl_context

    event = SDL_Event()

    while True:
        while SDL_PollEvent(ctypes.byref(event)) != 0:
            if event.type == SDL_QUIT:
                OpenGL.GL.glFinish()

                skia_context.flush()
                skia_context.submit()
                skia_context.abandonContext()

                SDL_GL_DeleteContext(gl_context)
                SDL_DestroyWindow(sdl_window)
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
