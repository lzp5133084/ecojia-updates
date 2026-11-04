# -*- coding: utf-8 -*-
"""
军哥懂保 · 全栈更新中心 —— EXE 通用自动更新模块（零依赖，复制即用）
作者：军哥懂保  微信：xunijiayuan   更新中心：https://ecojia.cn/updates/

接入方法（3 行代码）：
    from exe_updater import check_update
    check_update(appid="lead-radar", current_code=3, app_name="客资雷达")
    # appid 与更新中心注册的目录名一致；current_code 为当前版本整数号，每次发版 +1

工作原理：
    后台线程拉取 https://ecojia.cn/updates/<appid>/version.json → 比对 versionCode
    → 有新版则弹窗展示更新日志 → 用户点「立即更新」→ 下载到临时目录 → SHA256 校验
    → 生成更新助手批处理（等主程序退出→替换EXE→重启）→ 主程序退出，自动完成升级
注意：本模块不会静默替换任何文件，必须用户点击确认才会下载更新。
"""
import hashlib
import json
import os
import sys
import tempfile
import threading
import urllib.request

UPDATE_BASE = "https://ecojia.cn/updates"


def _fetch_manifest(appid, timeout=8):
    url = "%s/%s/version.json" % (UPDATE_BASE, appid)
    req = urllib.request.Request(url, headers={"User-Agent": "eco-updater/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def _sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 512), b""):
            h.update(chunk)
    return h.hexdigest()


def _ask_user(app_name, info):
    """弹窗询问是否更新；返回 True=立即更新。无界面库时默认不打扰。"""
    msg = "发现新版本 v%s（当前可在线升级）\n\n更新内容：\n%s\n\n点「立即更新」自动下载并升级，无需卸载旧版。" % (
        info.get("versionName", ""), info.get("changelog", "体验优化"))
    try:
        import tkinter as tk
        from tkinter import messagebox
        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        ok = messagebox.askyesno("%s 发现新版本" % app_name, msg, parent=root)
        root.destroy()
        return ok
    except Exception:
        return False  # 无 GUI 环境时静默跳过，绝不影响主程序


def _download(url, dst, timeout=120):
    req = urllib.request.Request(url, headers={"User-Agent": "eco-updater/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r, open(dst, "wb") as f:
        while True:
            chunk = r.read(1024 * 256)
            if not chunk:
                break
            f.write(chunk)


def _launch_helper_and_exit(old_exe, new_exe):
    """生成更新助手 bat：等主程序退出后替换并重启"""
    bat = os.path.join(tempfile.gettempdir(), "eco_update_helper.bat")
    pid = os.getpid()
    with open(bat, "w", encoding="gbk") as f:  # bat 用 gbk 避免中文路径乱码
        f.write("@echo off\r\n"
                "title 正在更新...\r\n"
                ":wait\r\n"
                "tasklist /FI \"PID eq %d\" | find \"%d\" >nul\r\n"
                "if not errorlevel 1 (ping -n 2 127.0.0.1 >nul & goto wait)\r\n"
                "move /y \"%s\" \"%s\" >nul\r\n"
                "start \"\" \"%s\"\r\n"
                "del /q \"%%~f0\"\r\n" % (pid, pid, new_exe, old_exe, old_exe))
    os.startfile(bat)  # noqa: S606
    os._exit(0)


def _launch_zip_helper_and_exit(install_dir, new_zip, restart_cmd):
    """ZIP 整包更新：等主程序退出→解压覆盖安装目录→按 restart_cmd 重启"""
    bat = os.path.join(tempfile.gettempdir(), "eco_update_helper.bat")
    pid = os.getpid()
    with open(bat, "w", encoding="gbk") as f:
        f.write("@echo off\r\n"
                "title 正在更新...\r\n"
                ":wait\r\n"
                "tasklist /FI \"PID eq %d\" | find \"%d\" >nul\r\n"
                "if not errorlevel 1 (ping -n 2 127.0.0.1 >nul & goto wait)\r\n"
                "powershell -NoProfile -Command \"Expand-Archive -Force '%s' '%s'\"\r\n"
                "start \"\" \"%s\"\r\n"
                "del /q \"%s\"\r\n"
                "del /q \"%%~f0\"\r\n" % (pid, pid, new_zip, install_dir, restart_cmd, new_zip))
    os.startfile(bat)  # noqa: S606
    os._exit(0)


def check_update(appid, current_code, app_name="", manifest=None, gui=True,
                 restart_cmd=None, install_dir=None):
    """
    启动时调用（非阻塞，立即返回）。
    appid: 更新中心注册名；current_code: 当前版本整数号；app_name: 弹窗标题用
    manifest: 可自定义清单地址；gui=False 时完全静默（仅打印日志）
    restart_cmd/install_dir: ZIP 整包更新时使用（解压覆盖 install_dir 后用 restart_cmd 重启）；
        不传则按单 EXE 替换处理。
    """
    app_name = app_name or appid

    def _work():
        try:
            info = _fetch_manifest(appid) if not manifest else json.loads(
                urllib.request.urlopen(urllib.request.Request(
                    manifest, headers={"User-Agent": "eco-updater/1.0"}), timeout=8).read().decode("utf-8"))
            if int(info.get("versionCode", 0)) <= int(current_code):
                return  # 已是最新
            url = info.get("exeUrl") or info.get("url")
            if not url:
                return  # 尚未发布在线包
            if gui and not _ask_user(app_name, info):
                return  # 用户选择下次再说
            is_zip = url.lower().endswith(".zip")
            new_pkg = os.path.join(tempfile.gettempdir(),
                                   "%s-update.%s" % (appid, "zip" if is_zip else "exe"))
            _download(url, new_pkg)
            expect = (info.get("sha256") or "").lower()
            if expect and _sha256(new_pkg) != expect:
                os.remove(new_pkg)
                print("[更新] 校验失败，已取消")
                return
            if is_zip:  # 整包覆盖更新
                target_dir = install_dir or os.path.dirname(os.path.abspath(sys.argv[0]))
                restart = restart_cmd or os.path.join(target_dir, "START.bat")
                _launch_zip_helper_and_exit(target_dir, new_pkg, restart)
            else:       # 单 EXE 替换更新
                old_exe = sys.executable if getattr(sys, "frozen", False) else os.path.abspath(sys.argv[0])
                _launch_helper_and_exit(old_exe, new_pkg)
        except Exception as e:
            print("[更新] 检查失败（不影响使用）: %s" % e)

    threading.Thread(target=_work, daemon=True).start()


if __name__ == "__main__":
    # 自检：拉取多码集清单并打印
    print(json.dumps(_fetch_manifest("duomaji"), ensure_ascii=False, indent=2))
