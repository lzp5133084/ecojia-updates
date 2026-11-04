# -*- coding: utf-8 -*-
"""
军哥懂保 · 全栈更新中心 —— 一键发版工具
作者：军哥懂保  微信：xunijiayuan   更新中心：https://ecojia.cn/updates/

用法：
    python publish.py <appid> <包路径.apk/.exe> <versionCode整数> <versionName> <更新说明>
示例：
    python publish.py lead-radar ./dist/客资雷达.exe 4 1.3.0 "新增B端商机筛选"
    python publish.py doubao-ball ./app-release.apk 8 1.5.0 "悬浮球支持拖动记忆位置"

做了什么：
    1. 上传安装包到更新中心（doubao-ball 同步镜像到 /doubao-ball/ 兼容老客户端）
    2. 自动计算 SHA256 与文件大小，重写 version.json 清单
    3. 更新 apps.json 的 updated 时间
    4. 线上验证清单生效
之后：所有装了旧版的设备，下次打开应用会自动弹窗提示更新。
"""
import hashlib
import json
import os
import sys
import urllib.request

import paramiko

HOST = "118.24.173.246"
USER = "ubuntu"
PASSWORD = "Lzp520520520."
BASE_DIR = "/opt/ecojia/updates"
BASE_URL = "https://ecojia.cn/updates"

# 历史兼容：doubao-ball 老客户端只认 /doubao-ball/ 路径，包需双写镜像
MIRROR = {
    "doubao-ball": {
        "pkg_dir": "/opt/ecojia/sites/doubao-ball",
        "pkg_url": "https://ecojia.cn/doubao-ball/doubao-ball-latest.apk",
        "pkg_name": "doubao-ball-latest.apk",
    }
}


def sha256_of(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def sh(client, cmd):
    _, out, err = client.exec_command(cmd, timeout=60)
    return out.read().decode("utf-8", "ignore"), err.read().decode("utf-8", "ignore")


def main():
    if len(sys.argv) < 6:
        print(__doc__)
        sys.exit(1)
    appid, pkg_path, vcode, vname, changelog = (
        sys.argv[1], sys.argv[2], int(sys.argv[3]), sys.argv[4], sys.argv[5])
    ext = os.path.splitext(pkg_path)[1].lower()
    assert ext in (".apk", ".exe", ".zip"), "只支持 .apk / .exe / .zip（整包）"
    platform = "apk" if ext == ".apk" else "exe"
    digest = sha256_of(pkg_path)
    size = os.path.getsize(pkg_path)
    print("[1/5] 包信息：%s  %.1f MB  sha256=%s..." % (ext, size / 1048576, digest[:12]))

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(HOST, username=USER, password=PASSWORD, timeout=20)

    app_dir = "%s/%s" % (BASE_DIR, appid)
    sh(client, "mkdir -p %s" % app_dir)
    sftp = client.open_sftp()

    # 包上传位置
    mirror = MIRROR.get(appid)
    if mirror:
        remote_pkg = "%s/%s" % (mirror["pkg_dir"], mirror["pkg_name"])
        pkg_url = mirror["pkg_url"]
    else:
        pkg_name = "%s-latest%s" % (appid, ext)
        remote_pkg = "%s/%s" % (app_dir, pkg_name)
        pkg_url = "%s/%s/%s" % (BASE_URL, appid, pkg_name)

    print("[2/5] 上传安装包 → %s" % remote_pkg)
    sftp.put(pkg_path, remote_pkg)

    # 清单（保留 apkUrl/exeUrl 兼容字段，老客户端读 apkUrl 不受影响）
    info = {
        "app": appid,
        "name": appid,
        "platform": platform,
        "versionCode": vcode,
        "versionName": vname,
        "url": pkg_url,
        "apkUrl": pkg_url if platform == "apk" else None,
        "exeUrl": pkg_url if platform == "exe" else None,
        "sha256": digest,
        "size": size,
        "changelog": changelog,
        "mandatory": False,
        "updated": __import__("datetime").date.today().isoformat(),
    }
    print("[3/5] 写入 version.json ...")
    with sftp.open("%s/version.json" % app_dir, "w") as f:
        f.write(json.dumps(info, ensure_ascii=False))
    if mirror:  # doubao-ball 兼容老清单地址
        legacy = {"versionCode": vcode, "versionName": vname, "apkUrl": pkg_url, "changelog": changelog}
        with sftp.open("%s/version.json" % mirror["pkg_dir"], "w") as f:
            f.write(json.dumps(legacy, ensure_ascii=False))

    # 更新 apps.json 的 updated
    print("[4/5] 更新 apps.json ...")
    out, _ = sh(client, "cat %s/apps.json" % BASE_DIR)
    apps = json.loads(out)
    apps["meta"]["updated"] = info["updated"]
    found = False
    for a in apps["apps"]:
        if a["app"] == appid:
            found = True
            break
    if not found:
        apps["apps"].append({
            "app": appid, "name": appid, "platform": platform, "desc": "",
            "manifest": "%s/%s/version.json" % (BASE_URL, appid), "home": "",
        })
    with sftp.open("%s/apps.json" % BASE_DIR, "w") as f:
        f.write(json.dumps(apps, ensure_ascii=False, indent=2))
    sftp.close()
    client.close()

    print("[5/5] 线上验证 ...")
    try:
        req = urllib.request.Request("%s/%s/version.json" % (BASE_URL, appid),
                                     headers={"User-Agent": "eco-publish/1.0"})
        with urllib.request.urlopen(req, timeout=15) as r:
            data = json.loads(r.read().decode("utf-8"))
            assert data["versionCode"] == vcode
        print("[成功] v%s (code=%d) 已生效：%s" % (vname, vcode, pkg_url))
    except Exception as e:
        print("[警告] 线上验证失败（可能有缓存，稍后重试）: %s" % e)
    print("完成！用户下次打开应用会自动提示更新。")


if __name__ == "__main__":
    main()
