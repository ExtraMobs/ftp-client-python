import enum
import ftplib
import hashlib
import os
import sys
from io import StringIO

SYNC_CLIENT = enum.auto()
SYNC_SERVER = enum.auto()


class FTPClient(ftplib.FTP):
    remote_hashes = {}
    local_hashes = {}
    
    def __init__(self, *arks, **kwargs) -> None:
        super().__init__(*arks, **kwargs)
        self.encoding = "utf-8"
        

    def get_directories(self, remote_path):
        """
        Returns a set of directories in the current directory on the FTP server

        Stdout output of self.dir() is redirected to an IO object and then
        reset, because self.dir() only prints its results to stdout.

        @param self: Open connection to FTP server
        @return: Set of directory names
        """
        # Redirect stdout
        old_stdout = sys.stdout
        sys.stdout = new_stdout = StringIO()
        # Get directory listing
        self.dir(remote_path)
        # Reset stdout
        sys.stdout = old_stdout

        directory_listing = new_stdout.getvalue().split("\n")
        # Directories are listed starting with "d" for "directory"
        only_directories = (x for x in directory_listing if x.startswith("d"))
        # This only deals with directory names without spaces.
        directory_names = set(
            dirname.split(":")[-1][3:] for dirname in only_directories
        )
        return directory_names

    def get_md5(self, remote_path):
        m = hashlib.md5()
        self.retrbinary(f"RETR {remote_path}", m.update)
        return m.hexdigest()

    def download_file(self, local_path, remote_path):
        with open(local_path, "wb") as file:
            self.retrbinary(f"RETR {remote_path}", file.write)

    def upload_file(self, local_path, remote_path):
        with open(os.path.abspath(local_path), "rb") as file:
            self.storbinary(f"STOR {remote_path}", file)

    def delete_file(self, local_path, remote_path):
        if local_path is not None:
            os.remove(local_path)
        if remote_path is not None:
            directories = self.get_directories(os.path.split(remote_path)[0])
            if os.path.basename(remote_path) not in directories:
                self.delete(remote_path)
                if remote_path in self.remote_hashes.keys():
                    del self.remote_hashes[remote_path]
            else:
                for item in self.nlst(remote_path):
                    self.delete_file(local_path, os.path.join(remote_path, item))
                self.rmd(remote_path)

    def sync(
        self,
        local_path,
        remote_path="",
        mode=SYNC_SERVER,
    ):
        local_path = local_path.replace("/", "\\")
        remote_path = remote_path.replace("/", "\\")
        if remote_path == "\\":
            remote_path = ""

        if not os.path.exists(local_path):
            os.makedirs(local_path)
        work_local_path = os.path.join(local_path, remote_path)

        local_items = (
            os.listdir(work_local_path) if os.path.exists(work_local_path) else []
        )
        try:
            remote_items = self.nlst(remote_path)
        except ftplib.error_perm:
            self.mkd(remote_path)
            remote_items = []

        diference_between_remote = set(local_items) ^ set(remote_items)
        to_download_list = list(diference_between_remote & set(remote_items))
        to_upload_list = list(diference_between_remote & set(local_items))

        directories = self.get_directories(remote_path)

        # Download
        for _, item in enumerate(remote_items):
            tmp_local_path = os.path.join(work_local_path, item)
            work_remote_path = os.path.join(remote_path, item)
            if item not in directories:
                self.remote_hashes[work_remote_path] = self.get_md5(work_remote_path)
            if mode == SYNC_SERVER:
                if not item in directories:
                    if item in local_items:
                        if not os.path.isdir(tmp_local_path):
                            need_download = os.path.getsize(tmp_local_path) != self.size(work_remote_path)
                    else:
                        need_download = True
                    if item in to_download_list and need_download:
                        print(item)
                        self.download_file(tmp_local_path, work_remote_path)
                else:
                    if not os.path.exists(tmp_local_path):
                        os.makedirs(tmp_local_path)
                    self.sync(local_path, work_remote_path, mode)
            elif mode == SYNC_CLIENT:
                if item in to_download_list:
                    self.delete_file(None, work_remote_path)
        # Upload
        for i, item in enumerate(local_items):
            tmp_local_path = os.path.join(work_local_path, item)
            work_remote_path = os.path.join(remote_path, item)
            if not os.path.isdir(tmp_local_path):
                m = hashlib.md5()
                m.update(open(tmp_local_path, "rb").read())
                self.local_hashes[tmp_local_path] = m.hexdigest()
            if mode in (SYNC_SERVER, SYNC_CLIENT):
                if not os.path.isdir(tmp_local_path):
                    if item in remote_items:
                        need_upload = (
                            self.local_hashes[tmp_local_path]
                            != self.remote_hashes[work_remote_path]
                        )
                    else:
                        need_upload = True

                    if need_upload:
                        try:
                            self.upload_file(tmp_local_path, work_remote_path)
                        except PermissionError:
                            ...
                else:
                    if item in to_upload_list:
                        self.sync(local_path, work_remote_path, mode)
