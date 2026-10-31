package com.phonehubmobile

import android.content.BroadcastReceiver
import android.content.ClipData
import android.content.ClipboardManager
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.media.AudioManager
import android.media.Ringtone
import android.media.RingtoneManager
import android.os.BatteryManager
import android.os.Environment
import org.json.JSONObject
import java.io.File
import java.io.FileOutputStream

/**
 * The "everything else" that makes PhoneHub a single all-in-one app over its own
 * WebSocket: battery reporting, two-way clipboard, and find-my-phone (ring).
 * Started when the link is READY, stopped on disconnect.
 */
class DeviceServices(
    private val ctx: Context,
    private val send: (JSONObject) -> Unit,
) {
    private val clipboard =
        ctx.getSystemService(Context.CLIPBOARD_SERVICE) as ClipboardManager
    private var batteryRx: BroadcastReceiver? = null
    private var ringtone: Ringtone? = null
    private val inbox = HashMap<String, FileOutputStream>()     // incoming files (laptop→phone)
    private val inboxName = HashMap<String, String>()

    fun start() {
        if (batteryRx != null) return
        batteryRx = object : BroadcastReceiver() {
            override fun onReceive(c: Context, i: Intent) = sendBattery(i)
        }
        // registerReceiver returns the current sticky battery intent immediately.
        val sticky = ctx.registerReceiver(batteryRx, IntentFilter(Intent.ACTION_BATTERY_CHANGED))
        sticky?.let { sendBattery(it) }
    }

    fun stop() {
        batteryRx?.let { try { ctx.unregisterReceiver(it) } catch (_: Exception) {} }
        batteryRx = null
        stopRing()
        synchronized(inbox) {
            inbox.values.forEach { try { it.close() } catch (_: Exception) {} }
            inbox.clear(); inboxName.clear()
        }
    }

    private fun sendBattery(i: Intent) {
        val level = i.getIntExtra(BatteryManager.EXTRA_LEVEL, -1)
        val scale = i.getIntExtra(BatteryManager.EXTRA_SCALE, -1)
        val pct = if (level >= 0 && scale > 0) level * 100 / scale else -1
        val status = i.getIntExtra(BatteryManager.EXTRA_STATUS, -1)
        val charging = status == BatteryManager.BATTERY_STATUS_CHARGING ||
            status == BatteryManager.BATTERY_STATUS_FULL
        send(JSONObject().apply {
            put("t", "battery"); put("level", pct); put("charging", charging)
        })
    }

    /** Control messages routed from Connection. Returns true if consumed. */
    fun handleControl(msg: JSONObject): Boolean {
        when (msg.optString("t")) {
            "clipboard" -> setClipboard(msg.optString("text"))
            "get_clipboard" -> sendClipboard()
            "ring" -> ring()
            "ring_stop" -> stopRing()
            "file_offer" -> openInbox(msg)        // laptop → phone (drag-drop)
            "file_done" -> closeInbox(msg.optString("transferId"))
            else -> return false
        }
        return true
    }

    /** Incoming binary frame. Channel 0x01 = file chunk: [0x01][8 ascii tid][bytes]. */
    fun handleBinary(raw: ByteArray): Boolean {
        if (raw.size < 9 || raw[0].toInt() != 0x01) return false
        val tid = String(raw, 1, 8, Charsets.US_ASCII)
        val fos = synchronized(inbox) { inbox[tid] }
        try { fos?.write(raw, 9, raw.size - 9) } catch (_: Exception) {}
        return true
    }

    private fun openInbox(msg: JSONObject) {
        val tid = msg.optString("transferId")
        val name = File(msg.optString("name", "file")).name.ifEmpty { "file" }
        try {
            val dir = ctx.getExternalFilesDir(Environment.DIRECTORY_DOWNLOADS) ?: ctx.filesDir
            dir.mkdirs()
            val out = File(dir, name)
            synchronized(inbox) {
                inbox[tid] = FileOutputStream(out)
                inboxName[tid] = out.absolutePath
            }
            send(JSONObject().apply { put("t", "file_accept"); put("transferId", tid) })
        } catch (_: Exception) {}
    }

    private fun closeInbox(tid: String) {
        val fos = synchronized(inbox) { inbox.remove(tid) }
        val path = synchronized(inbox) { inboxName.remove(tid) }
        try { fos?.close() } catch (_: Exception) {}
        if (path != null) {
            send(JSONObject().apply { put("t", "file_saved"); put("path", path) })
        }
    }

    fun setClipboard(text: String) {
        if (text.isEmpty()) return
        try { clipboard.setPrimaryClip(ClipData.newPlainText("PhoneHub", text)) } catch (_: Exception) {}
    }

    fun sendClipboard() {
        val text = try {
            clipboard.primaryClip?.getItemAt(0)?.coerceToText(ctx)?.toString()
        } catch (_: Exception) { null }
        if (!text.isNullOrEmpty()) {
            send(JSONObject().apply { put("t", "clipboard"); put("text", text) })
        }
    }

    fun ring() {
        try {
            val am = ctx.getSystemService(Context.AUDIO_SERVICE) as AudioManager
            am.setStreamVolume(
                AudioManager.STREAM_ALARM,
                am.getStreamMaxVolume(AudioManager.STREAM_ALARM), 0,
            )
            stopRing()
            val uri = RingtoneManager.getDefaultUri(RingtoneManager.TYPE_ALARM)
                ?: RingtoneManager.getDefaultUri(RingtoneManager.TYPE_RINGTONE)
            ringtone = RingtoneManager.getRingtone(ctx, uri)?.also { it.play() }
        } catch (_: Exception) {}
    }

    private fun stopRing() {
        try { ringtone?.stop() } catch (_: Exception) {}
        ringtone = null
    }
}
