from PyQt5.QtWidgets import QMainWindow, QMessageBox
from PyQt5.uic import loadUi
from PyQt5.QtGui import QCloseEvent, QIcon

from lib.load_piximage import load_piximage_from_url
from threading import Thread
from pytube import Stream
from pytube.helpers import safe_filename

from threads.object_handle import VideoDownloadHandleThread, MergeStreamsHandle, RemoveUnmergedHandle

from filesize import naturalsize
from os.path import basename, dirname, join, exists
from os import startfile, remove
from sys import exit
from lib.dirs import playground_dir
from lib.subtitle import Subtitle


class VideoDownloadWindow(QMainWindow):
    def __init__(self, download_data: dict, parent):
        super(VideoDownloadWindow, self).__init__()
        self.setWindowIcon(QIcon("./_internal/media-download.ico"))
        loadUi("./gui/video download", self)
        self.download_data = download_data
        self.display_data()
        self.key_bindings()
        self.setWindowTitle(download_data["title"])
        self.main_window = parent

        # declare the window manipulators
        self.download_handle = None
        self.merge_handle = None
        self.remove_unmerged_handle = None
        self.tasks = {}
        self.current_task = 0
        self.pause = False

    def key_bindings(self):
        self.pause_resume_btn.clicked.connect(self.pause_resume)
        self.cancel_btn.clicked.connect(self.close)

    def display_data(self):
        # displaying video details
        self.title.setText(self.download_data["title"])
        self.author.setText(self.download_data["author"])
        self.length.setText(self.download_data["length"])
        self.quality.setText(self.download_data["quality"])
        self.size.setText(self.download_data["size"])
        self.url.setText(self.download_data["url"])
        self.location.setText(self.download_data["location"])
        Thread(target=self.display_thumbnail, daemon=True).start()

    def display_thumbnail(self):
        piximage = load_piximage_from_url(self.download_data["thumbnail"])
        if piximage:
            self.img_1.setPixmap(piximage.scaledToWidth(243))
            self.img_2.setPixmap(piximage.scaledToWidth(243))
        else:
            self.img_1.setStyleSheet(
                self.img_1.styleSheet() + "color: #f32013;")
            self.img_2.setStyleSheet(
                self.img_2.styleSheet() + "color: #f32013;")
            self.img_1.setText("Failed!")
            self.img_2.setText("Failed!")

    def display_download_stat(self, stat: dict):
        # TODO: refine data displayed
        # display rate if found
        # display estimated time if found

        self.rate.setText(naturalsize(stat['rate']))
        self.estimated.setText(
            f"Size: {naturalsize(stat['estimated_size'])}      Time: {stat['estimated_time']}")
        self.downloaded.setText(str(naturalsize(stat["downloaded"])))
        self.progress.setValue(stat["progress"])
        self.progress_label.setText(f"Progress:    {stat['progress']}%")

    def display_merging_stat(self, stat: dict, show_status: bool = False):
        if show_status:
            self.statusBar().showMessage(
                f"Performing merging tasks ({stat['current']}/{stat['total']})")
            return
        self.rate.setText(f"merging: {stat['rate']}")
        self.estimated.setText(f"Time: {stat['estimated_time']}")
        self.progress.setValue(stat['progress'])
        self.progress_label.setText(f"Progress:    {stat['progress']}%")

    def show_merging_status(self, current, total):
        self.statusBar().showMessage(
            f"Performing merging tasks ({current}/{total})")

    def define_tasks(self):
        stream_type = self.download_data["stream_type"]
        if stream_type == "video" or stream_type == "audio":
            self.tasks = {0: {
                "type": stream_type,
                "done": False
            }}

        else:
            self.tasks = {
                0: {
                    "type": "video",
                    "done": False,
                },
                1: {
                    "type": "audio",
                    "done": False,
                },
                2: {
                    "type": "merging",
                    "done": False,
                }
            }
        self.manage_tasks()

    def manage_tasks(self):
        current_task = self.tasks.get(self.current_task)
        if current_task is not None:

            if current_task["type"] == "video" or current_task["type"] == "audio":
                # handling stream downloading whether audio or video stream
                if self.download_data["stream_type"] == "unmerged":
                    location = join(playground_dir, basename(self.download_data["location"])) + (
                        " (audio)" if current_task["type"] == "audio" else "")
                else:
                    location = self.download_data["location"]

                self.download_stream(stream=self.download_data[f"{current_task['type']}_stream_object"],
                                     file_path=location,
                                     stream_type=current_task["type"])
            else:
                self.statusBar().showMessage("Performing merging tasks .. DO NOT CLOSE THE PROGRAM!")
                # handle merging
                clip_location = join(playground_dir, basename(
                    self.download_data["location"]))
                self.cancel_btn.setEnabled(False)
                self.pause_resume_btn.setEnabled(False)
                self.merge_streams(
                    clip_location, self.download_data["location"])

        else:
            if self.download_data["subtitle_index"] != "no subtitle":
                self.cancel_btn.setEnabled(False)
                self.pause_resume_btn.setEnabled(False)
                self.statusBar().showMessage("Downloading subtitle ..")
                stream_type = "audio" if self.download_data["stream_type"] == "audio" else "video"
                Thread(target=self.download_subtuitle,
                       kwargs={
                           "subtitle": self.download_data["subtitle_object"],
                           "index": self.download_data["subtitle_index"],
                           "stream_object": self.download_data[f"{stream_type}_stream_object"]
                       },
                       daemon=True).start()
            print("All tasks completed")  # Added this debug print
            self.statusBar().showMessage("All tasks finished")
            self.on_tasks_finished()

    def next_task(self):
        print("next_task called")  # Added this debug print
        self.tasks[self.current_task]["done"] = True
        self.current_task += 1
        self.manage_tasks()

    def download_stream(self, stream: Stream, file_path, stream_type: str):
        # stop and wait for previous tasks' threads
        if self.download_handle:
            self.download_handle.analyzer.quit()
            self.download_handle.analyzer.wait()
            self.download_handle.quit()
            self.download_handle.wait()

        self.download_handle = VideoDownloadHandleThread(
            stream=stream,
            file_path=file_path,
            filesize=stream.filesize
        )
        self.download_handle.download_stat.connect(self.display_download_stat)
        self.download_handle.analyzer.completed.connect(
            self.next_task)  # Connected the completed signal
        self.download_handle.on_error.connect(self.on_error)
        self.download_handle.on_download_finish.connect(
            self.next_task)  # Connected the on_download_finish signal
        self.download_handle.start()
        self.statusBar().showMessage(f"downloading {stream_type} ..")

    def merge_streams(self, clip_location, location):
        self.merge_handle = MergeStreamsHandle(clip_location, location)
        self.merge_handle.merging_stat.connect(self.display_merging_stat)
        self.merge_handle.show_status.connect(self.show_merging_status)
        self.merge_handle.finished.connect(
            lambda: self.remove_clips(clip_location))
        self.merge_handle.finished.connect(
            self.next_task)  # Connect the finished signal
        self.merge_handle.on_error.connect(self.on_error)
        self.merge_handle.start()
        self.statusBar().showMessage("Performing merging tasks .. DO NOT CLOSE THE PROGRAM!")

    def download_subtuitle(self, subtitle: Subtitle, index: int, stream_object: Stream):
        file_name = f"{safe_filename(stream_object.title)} - {subtitle.get_lang_code(index=index)}.srt"
        file_path = join(dirname(self.download_data["location"]), file_name)
        try:
            text = subtitle.generate_srt_format(index=index)
            with open(file_path, "w", encoding="utf-8") as srt:
                srt.write(text)
                srt.close()
        except Exception as e:
            print(e)
            self.statusBar().showMessage("Couldn't download subtitle!")

    def remove_clips(self, clip_location):
        self.remove_unmerged_handle = RemoveUnmergedHandle(clip_location)
        self.remove_unmerged_handle.finished.connect(self.next_task)
        self.remove_unmerged_handle.on_error.connect(
            self.on_remove_unmerged_error)
        self.remove_unmerged_handle.start()

    def pause_resume(self):
        if self.pause:
            self.pause = False
            self.manage_tasks()
            self.pause_resume_btn.setText("Pause")
        else:
            self.pause = True
            self.download_handle.analyzer.stop()
            self.download_handle.terminate()
            self.download_handle.wait()
            self.pause_resume_btn.setText("Resume")
            self.statusBar().showMessage("download paused")

    def closeEvent(self, a0: QCloseEvent) -> None:
        if not self.pause:
            self.pause_resume()
        a0.accept()

    def on_tasks_finished(self):
        print("Tasks finished")  # Added this debug print
        file_path = self.download_data['location']
        msg = QMessageBox(parent=self)
        msg.setWindowTitle("Download Finished")
        msg.setIcon(QMessageBox.Information)
        msg.setText(basename(file_path))
        msg.addButton("open", QMessageBox.AcceptRole)
        msg.addButton("open folder", QMessageBox.AcceptRole)
        msg.addButton("download another", QMessageBox.AcceptRole)
        msg.addButton("exit", QMessageBox.AcceptRole)
        btn = msg.exec()

        if btn == 0:
            startfile(file_path)
        elif btn == 1:
            startfile(dirname(file_path))
        elif btn == 2:
            self.prepare_another()
            return
        exit()

    def on_error(self):
        msg = QMessageBox(parent=self)
        msg.setWindowTitle("Error!")
        msg.setIcon(QMessageBox.Critical)
        msg.setText(
            f"Error happened while downloading {self.download_data['title']}")
        msg.addButton("Try again", QMessageBox.AcceptRole)
        msg.addButton("Exit", QMessageBox.AcceptRole)
        btn = msg.exec()

        if btn == 0:
            self.manage_tasks()
        else:
            exit()

    def on_remove_unmerged_error(self, clip_location):
        msg = QMessageBox(parent=self)
        msg.setWindowTitle("Error!")
        msg.setIcon(QMessageBox.Critical)
        msg.setText(f"Couldn't delete\n{clip_location}\ntry delete it")
        msg.addButton("Exit", QMessageBox.RejectRole)
        btn = msg.exec()

    def prepare_another(self):
        self.hide()
        self.main_window.reset_gui()
        self.main_window.show()
