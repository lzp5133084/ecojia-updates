package com.junge.doubaoball

import android.app.AlertDialog
import android.app.DownloadManager
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.net.Uri
import android.os.Build
import android.os.Environment
import android.widget.Toast
import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.URL
import java.security.MessageDigest
import kotlin.concurrent.thread

/**
 * 军哥懂保 · 全栈更新中心 —— APK 通用自动更新模块（复制即用）
 * 作者：军哥懂保  微信：xunijiayuan   更新中心：https://ecojia.cn/updates/
 *
 * 接入方法（在 MainActivity.onCreate 里加一行）：
 *   UpdateChecker.check(this, "https://ecojia.cn/updates/你的应用/version.json", "你的应用名")
 *
 * 服务器清单 version.json 约定：
 *   {"versionCode":8,"versionName":"1.5.0","apkUrl":"https://.../xxx.apk","changelog":"...","sha256":"可选"}
 *
 * 流程：启动静默检查 → 有新版弹窗展示更新日志 → 用户点「立即更新」
 *   → 系统下载器下载 → （可选）SHA256 校验 → 自动跳系统安装（覆盖安装，数据不丢）
 * 安卓系统限制：安装那一步系统一定会弹确认框，这是系统安全要求，无法跳过。
 */
object UpdateChecker {

    private var manifestUrl: String = "https://ecojia.cn/updates/doubao-ball/version.json"
    private var appLabel: String = "应用"

    /** 静默检查（启动时调用）：网络失败不打扰用户 */
    fun check(context: Context, url: String? = null, appName: String? = null) {
        url?.let { manifestUrl = it }
        appName?.let { appLabel = it }
        thread {
            try {
                val conn = URL(manifestUrl).openConnection() as HttpURLConnection
                conn.connectTimeout = 6000
                conn.readTimeout = 6000
                conn.useCaches = false
                val body = conn.inputStream.bufferedReader().readText()
                conn.disconnect()

                val json = JSONObject(body)
                val remoteCode = json.getInt("versionCode")
                val remoteName = json.optString("versionName", "")
                val apkUrl = json.optString("apkUrl", json.optString("url", ""))
                val changelog = json.optString("changelog", "体验优化")
                val sha256 = json.optString("sha256", "")

                val localCode = context.packageManager
                    .getPackageInfo(context.packageName, 0).versionCode

                if (remoteCode > localCode && apkUrl.startsWith("http")) {
                    (context as? MainActivity)?.runOnUiThread {
                        showUpdateDialog(context, remoteName, apkUrl, changelog, sha256)
                    }
                }
            } catch (e: Exception) {
                // 静默失败：服务器没连上不影响正常使用
            }
        }
    }

    private fun showUpdateDialog(
        context: Context, versionName: String, apkUrl: String, changelog: String, sha256: String
    ) {
        AlertDialog.Builder(context)
            .setTitle("发现新版本 v$versionName")
            .setMessage("更新内容：\n$changelog\n\n点「立即更新」自动下载安装，不用删旧版。")
            .setPositiveButton("立即更新") { _, _ -> downloadAndInstall(context, apkUrl, sha256) }
            .setNegativeButton("下次再说", null)
            .show()
    }

    /** 系统下载器下载 APK → 可选校验 → 自动跳安装 */
    private fun downloadAndInstall(context: Context, apkUrl: String, sha256: String) {
        val dm = context.getSystemService(Context.DOWNLOAD_SERVICE) as DownloadManager
        val request = DownloadManager.Request(Uri.parse(apkUrl)).apply {
            setTitle("$appLabel 新版本")
            setDescription("正在下载更新包…")
            setNotificationVisibility(DownloadManager.Request.VISIBILITY_VISIBLE_NOTIFY_COMPLETED)
            setDestinationInExternalPublicDir(Environment.DIRECTORY_DOWNLOADS, "$appLabel-update.apk")
            setMimeType("application/vnd.android.package-archive")
        }
        val downloadId = dm.enqueue(request)
        Toast.makeText(context, "开始下载，完成后会自动弹出安装", Toast.LENGTH_LONG).show()

        val receiver = object : BroadcastReceiver() {
            override fun onReceive(ctx: Context, intent: Intent) {
                if (intent.getLongExtra(DownloadManager.EXTRA_DOWNLOAD_ID, -1) != downloadId) return
                runCatching { ctx.unregisterReceiver(this) }
                val uri = dm.getUriForDownloadedFile(downloadId) ?: return

                // 可选 SHA256 校验：不一致则拒绝安装
                if (sha256.isNotBlank()) {
                    val actual = runCatching { sha256Of(ctx, uri) }.getOrNull()
                    if (actual == null || !actual.equals(sha256, ignoreCase = true)) {
                        Toast.makeText(ctx, "更新包校验失败，已取消安装", Toast.LENGTH_LONG).show()
                        return
                    }
                }
                val install = Intent(Intent.ACTION_VIEW).apply {
                    setDataAndType(uri, "application/vnd.android.package-archive")
                    addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION or Intent.FLAG_ACTIVITY_NEW_TASK)
                }
                ctx.startActivity(install)
            }
        }
        val filter = IntentFilter(DownloadManager.ACTION_DOWNLOAD_COMPLETE)
        if (Build.VERSION.SDK_INT >= 33) {
            context.registerReceiver(receiver, filter, Context.RECEIVER_EXPORTED)
        } else {
            @Suppress("UnspecifiedRegisterReceiverFlag")
            context.registerReceiver(receiver, filter)
        }
    }

    private fun sha256Of(ctx: Context, uri: Uri): String {
        val md = MessageDigest.getInstance("SHA-256")
        ctx.contentResolver.openInputStream(uri)?.use { ins ->
            val buf = ByteArray(512 * 1024)
            while (true) {
                val n = ins.read(buf)
                if (n <= 0) break
                md.update(buf, 0, n)
            }
        }
        return md.digest().joinToString("") { "%02x".format(it) }
    }
}
