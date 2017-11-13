#! /usr/bin/env python3.6

import json
import operator as op
import os
import platform
import tkinter as tk
from contextlib import suppress
from idlelib.redirector import WidgetRedirector
from itertools import groupby
from tkinter.filedialog import askopenfilename, asksaveasfilename
from typing import List, Tuple, Optional, Dict


BREAK = "break"
TEXTSTART = "1.0"
# buttons and keys
RCLICK = "<Button-2>" if platform.system() == "Darwin" else "<Button-3>"
KEY = "<Key>"
SELECT_KEY = "S"
DESELECT_KEY = "D"
# status labels
HIGH = True
LOW = False
# text tag
HIGH_TAG = "high"

# Markup = Tuple[start, stop, status (either HIGH or LOW)]
Markup = Tuple[int, int, bool]


class Checkpoint:
    def __init__(self, path):
        try:
            with open(path) as buffer:
                self.data: Dict = json.load(buffer)
        except (OSError, IOError, AttributeError, json.JSONDecodeError):
            raise RuntimeError("Bad input")
        if "head" not in self.data or "frames" not in self.data:
            raise RuntimeError("Bad input")

    def __len__(self):
        return len(self.data["frames"])

    @property
    def head(self) -> int:
        """
        Current head frame
        :return:
        """
        return self.data["head"]

    @head.setter
    def head(self, pos: int):
        if not 0 <= pos < len(self):
            raise ValueError("New head is outside the available range")
        # cleanup current head
        self.fanno = self.cleanup(self.fanno)
        self.data["head"] = pos

    @property
    def frame(self) -> dict:
        """
        Return the head frame
        :return:
        """
        return self.data["frames"][self.head]

    @property
    def ftext(self) -> str:
        """
        Return head frame's text
        :return:
        """
        return self.frame["text"]

    @property
    def fanno(self) -> List[Markup]:
        """
        Return head frame's annotation (highlighted intervals)
        :return: a list of annotations, i.e. (start, stop, action)
        """
        return self.frame["anno"]

    @fanno.setter
    def fanno(self, value):
        self.frame["anno"] = value

    @staticmethod
    def cleanup(markups: List[Markup]) -> List[Markup]:
        if not markups:
            return []
        maxpos = max(map(op.itemgetter(1), markups)) - 1
        annotation = [0] * maxpos
        for start, stop, status in markups:
            length = stop - start
            annotation[start:stop] = [status] * length
        runs = groupby(enumerate(annotation), op.itemgetter(1))
        positive = [list(map(op.itemgetter(0), run)) for status, run in runs
                    if status == HIGH]
        return [(run[0], run[-1] + 1, HIGH) for run in positive]

    def save(self, path: str) -> None:
        # cleanup current head
        self.fanno = self.cleanup(self.fanno)
        with open(path, "w") as outstream:
            json.dump(self.data, outstream)

    @property
    def isfinal(self) -> bool:
        """
        The head node is final one
        :return:
        """
        return self.head == len(self) - 1

    @property
    def isfirst(self) -> bool:
        """
        The head node is the first one
        :return:
        """
        return self.head == 0


class StaleText(tk.Text):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.redirector = WidgetRedirector(self)
        self.insert = self.redirector.register("insert", lambda *a, **k: BREAK)
        self.delete = self.redirector.register("delete", lambda *a, **k: BREAK)


class AnnotationApp:
    def __init__(self):
        self.master = tk.Tk()

        # Main menu
        self.menubar = tk.Menu(master=self.master)
        self.fmenu = tk.Menu(self.menubar, tearoff=0)
        self.fmenu.add_command(label="Open", command=self.open)
        self.fmenu.add_command(label="Save", command=self.save)
        self.menubar.add_cascade(label="File", menu=self.fmenu)
        self.master.configure(menu=self.menubar)

        # # Context menu
        # self.popup_menu = tk.Menu(self.master, tearoff=0)
        # self.popup_menu.add_command(label="Add", command=self.add)
        # self.popup_menu.add_command(label="Remove", command=self.remove)

        # Text window
        self.text = StaleText(self.master)
        self.text.tag_config(HIGH_TAG, background="red", foreground="white")
        self.text.tag_bind(HIGH_TAG, RCLICK, self.tagclick)
        self.text.bind(KEY, self.keypress)
        self.text.config(insertbackground="white")
        self.text.configure(font="arial 18")
        self.text.pack()

        # Move buttons and orientation
        self.bnext = tk.Button(master=self.master, text="Next Step",
                               state=tk.DISABLED,
                               command=self.next)
        self.bnext.pack(side=tk.RIGHT)
        self.bprev = tk.Button(master=self.master, text="Prev Step",
                               state=tk.DISABLED,
                               command=self.prev)
        self.bprev.pack(side=tk.LEFT)
        self.status = tk.Label(master=self.master, text="Open a file to begin")
        self.status.pack(side=tk.BOTTOM)

        # Examples
        self.checkpoint: Optional[Checkpoint] = None

    # def popup(self, event):
    #     """
    #     Open the context menu
    #     :param event:
    #     :return:
    #     """
    #     try:
    #         self.popup_menu.tk_popup(event.x_root, event.y_root, 0)
    #     finally:
    #         self.popup_menu.grab_release()

    def tagclick(self, event):
        # get the index of the mouse click
        index = event.widget.index("@{},{}".format(event.x, event.y))
        # get the indices of all "adj" tags
        tag_indices = list(event.widget.tag_ranges(HIGH_TAG))

        # iterate them pairwise (start and end index)
        for start, end in zip(tag_indices[0::2], tag_indices[1::2]):
            # check if the tag matches the mouse click index
            if (event.widget.compare(start, "<=", index) and
                    event.widget.compare(index, "<", end)):
                self.remove(start, end)

    def add(self, first_idx, last_idx) -> None:
        """
        Add current selection to highlighted annotations
        :return:
        """
        with suppress(TypeError):
            start, stop = self.text_range(first_idx, last_idx)
            self.checkpoint.fanno.append((start, stop, HIGH))
            self.highlight(start, stop)

    def remove(self, first_idx, last_idx) -> None:
        """
        Add current selection to ignored (low) annotations
        :return:
        """
        with suppress(TypeError):
            start, stop = self.text_range(first_idx, last_idx)
            self.checkpoint.fanno.append((start, stop, LOW))
            self.lower(start, stop)
            # print("removing ({} {})".format(start, stop))

    def keypress(self, event):
        with suppress(tk.TclError):
            if event.char.upper() == SELECT_KEY:
                self.add(tk.SEL_FIRST, tk.SEL_LAST)
            elif event.char.upper() == DESELECT_KEY:
                self.remove(tk.SEL_FIRST, tk.SEL_LAST)
            else:
                return BREAK

    def highlight(self, start, stop):
        """
        Highlight text from start to stop
        :param start:
        :param stop:
        :return:
        """
        idx1, idx2 = self.text_indices(start, stop)
        self.text.tag_add(HIGH_TAG, idx1, idx2)

    def lower(self, start, stop):
        """
        Remove highlighting from start to stop
        :param start:
        :param stop:
        :return:
        """
        idx1, idx2 = self.text_indices(start, stop)
        self.text.tag_remove("high", idx1, idx2)

    @staticmethod
    def text_indices(start: int, stop: int) -> Tuple[str, str]:
        """
        Convert a text span into Text widget indices
        :param start:
        :param stop:
        :return:
        """
        idx1 = "{} + {} chars".format(TEXTSTART, start)
        idx2 = "{} + {} chars".format(TEXTSTART, stop)
        return idx1, idx2

    def text_range(self, first_idx, last_idx) -> Optional[Tuple[int, int]]:
        """
        Return selected text range
        :return:
        """
        with suppress(tk.TclError):
            start = (self.text.count(TEXTSTART, first_idx) or [0])[0]
            stop = self.text.count(TEXTSTART, last_idx)[0]
            return start, stop

    def open(self) -> None:
        """
        Read a checkpoint file and activate the process
        :return:
        """
        path = os.path.abspath(askopenfilename(parent=self.master))
        checkpoint = Checkpoint(path)
        if not len(checkpoint):
            self.setstatus("The file is empty – try another one!")
            return
        self.checkpoint = checkpoint
        self.bprev.config(state=tk.NORMAL)
        self.bnext.config(state=tk.NORMAL)
        self.putframe(self.checkpoint.ftext, self.checkpoint.fanno)
        self.update_status()

    def save(self) -> None:
        """
        Saave a checkpoint file
        :return:
        """
        try:
            path = os.path.abspath(asksaveasfilename(parent=self.master,
                                                     defaultextension=".check"))
            self.checkpoint.save(path)
            self.setstatus("Successfully saved a checkpoint")
        except (OSError, IOError):
            self.setstatus("Can't save into that location")
        except AttributeError:
            self.setstatus("Nothing to save")

    def next(self):
        """
        Move to the next example
        :return:
        """
        if self.checkpoint.isfinal:
            return
        self.checkpoint.head = self.checkpoint.head + 1
        self.putframe(self.checkpoint.ftext, self.checkpoint.fanno)
        self.update_status()

    def prev(self):
        """
        Move to the previous example
        :return:
        """
        if self.checkpoint.isfirst:
            return
        self.checkpoint.head = self.checkpoint.head - 1
        self.putframe(self.checkpoint.ftext, self.checkpoint.fanno)
        self.update_status()

    def putframe(self, text: str, annotations: List[Markup]):
        """
        Insert annotated text into the Text widget
        :param text:
        :param annotations:
        :return:
        """
        self.text.delete(TEXTSTART, tk.END)
        self.text.insert(TEXTSTART, text)
        for start, stop in (span for *span, status in annotations if status is HIGH):
            self.highlight(start, stop)

    def setstatus(self, msg: str):
        """
        Set the status widget
        :param msg:
        :return:
        """
        self.status.config(text=msg)

    def update_status(self):
        """
        Update current example number
        :return:
        """
        self.setstatus(
            "{} / {}".format(self.checkpoint.head+1, len(self.checkpoint))
        )

    def main(self):
        self.master.title("AnnoHelper")
        self.master.resizable(width=False, height=False)
        self.master.mainloop()


if __name__ == '__main__':
    AnnotationApp().main()
