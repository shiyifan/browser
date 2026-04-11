import tkinter
import tkinter.font

WIDTH, HEIGHT = 800, 600


def main():
    print('a', end="")
    print('b', end="")
    print('c')
    # canvas = prepare()

    # f0 = tkinter.font.Font(size=20)
    # f1 = tkinter.font.Font(size=15)
    # canvas.create_text(20, 20, text="H", anchor="nw", font=f0)
    # canvas.create_text(20 + f0.measure("H"), 20, text="Hello", anchor="nw", font=f1)

    # tkinter.mainloop()


def prepare():
    window = tkinter.Tk()
    canvas = tkinter.Canvas(window, width=WIDTH, height=HEIGHT)
    canvas.pack()
    center(window)

    return canvas


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
