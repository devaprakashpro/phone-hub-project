package com.phonehubmobile

import android.app.Activity
import android.content.Intent
import android.media.projection.MediaProjectionManager
import androidx.core.content.ContextCompat
import com.facebook.react.bridge.*
import com.facebook.react.modules.core.DeviceEventManagerModule
import org.json.JSONObject
import java.io.InputStream

/**
 * JS-facing bridge. JS calls connect()/sendPin(); we emit 'state' and 'needPin'.
 * The WebSocket + video encoder stay native. Screen-capture consent is raised
 * here (we're an ActivityEventListener) and handed to HubService.
 */
class HubModule(private val reactContext: ReactApplicationContext) :
    ReactContextBaseJavaModule(reactContext), ActivityEventListener {

    init { reactContext.addActivityEventListener(this) }

    private var services: DeviceServices? = null

    override fun getName() = "Hub"

    private fun emit(event: String, data: Any?) {
        reactContext.getJSModule(DeviceEventManagerModule.RCTDeviceEventEmitter::class.java)
            .emit(event, data)
    }

    /** Create the shared Connection with all callbacks, if not already present. */
    private fun ensureConnection(): Connection {
        if (services == null) {
            services = DeviceServices(reactContext) { Hub.connection?.send(it) }
        }
        Hub.connection?.let { return it }
        val conn = Connection(
            ctx = reactContext,
            onState = { state ->
                // Battery/clipboard/ring come alive once the link is ready.
                if (state == "READY") services?.start() else if (state == "DISCONNECTED") services?.stop()
                emit("state", state)
            },
            onControl = { msg ->
                if (services?.handleControl(msg) != true) handleControl(msg)
            },
            onNeedPin = { emit("needPin", null) },
            onBinary = { services?.handleBinary(it) },   // incoming files (laptop→phone)
        )
        Hub.connection = conn
        return conn
    }

    @ReactMethod
    fun connect(host: String, port: Int) {
        Hub.connection?.close()
        Hub.connection = null
        val conn = ensureConnection()
        startLinkService()              // keep the process/link alive in background
        conn.connect(host, port)
    }

    /** On app launch: silently re-link to the laptop from a previous pairing. */
    @ReactMethod
    fun autoConnect(promise: Promise) {
        val conn = ensureConnection()
        val ok = conn.reconnectSaved()
        if (ok) startLinkService()
        promise.resolve(ok)
    }

    @ReactMethod
    fun disconnect() {
        services?.stop()
        Hub.connection?.close()
        Hub.connection = null
        stopLinkService()
        emit("state", "DISCONNECTED")
    }

    private fun startLinkService() {
        try {
            ContextCompat.startForegroundService(
                reactContext, Intent(reactContext, LinkService::class.java))
        } catch (_: Exception) {}
    }

    private fun stopLinkService() {
        try { reactContext.stopService(Intent(reactContext, LinkService::class.java)) } catch (_: Exception) {}
    }

    /** Push the phone clipboard to the laptop (JS button). */
    @ReactMethod
    fun sendClipboard() { services?.sendClipboard() }

    /** Pick a file and stream it to the laptop over the WebSocket. */
    @ReactMethod
    fun sendFile() {
        val act = reactContext.currentActivity ?: return
        val pick = Intent(Intent.ACTION_GET_CONTENT).apply {
            type = "*/*"
            addCategory(Intent.CATEGORY_OPENABLE)
        }
        act.startActivityForResult(Intent.createChooser(pick, "Send to laptop"), REQ_PICK_FILE)
    }

    @ReactMethod
    fun sendPin(pin: String) { Hub.connection?.sendPin(pin) }

    /** Open the system screens where the user grants the two optional powers. */
    @ReactMethod
    fun openNotificationAccess() {
        open(android.provider.Settings.ACTION_NOTIFICATION_LISTENER_SETTINGS)
    }

    @ReactMethod
    fun openAccessibilitySettings() {
        open(android.provider.Settings.ACTION_ACCESSIBILITY_SETTINGS)
    }

    private fun open(action: String) {
        try {
            reactContext.startActivity(Intent(action).apply {
                addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
            })
        } catch (_: Exception) {}
    }

    /** Report which optional powers are live so the UI can nudge the user. */
    @ReactMethod
    fun getPermissions(promise: Promise) {
        val map = Arguments.createMap()
        val enabled = android.provider.Settings.Secure.getString(
            reactContext.contentResolver, "enabled_notification_listeners") ?: ""
        map.putBoolean("notifications", enabled.contains(reactContext.packageName))
        map.putBoolean("control", InputService.instance != null)
        promise.resolve(map)
    }

    /** Phone-initiated mirror: raise the system capture consent, then stream. */
    @ReactMethod
    fun startMirror() { requestProjection() }

    @ReactMethod
    fun stopMirror() {
        reactContext.startService(Intent(reactContext, HubService::class.java)
            .apply { action = HubService.ACTION_STOP_MIRROR })
    }

    private fun handleControl(msg: JSONObject) {
        when (msg.optString("t")) {
            "mirror_start" -> requestProjection()
            "mirror_stop" -> reactContext.startService(
                Intent(reactContext, HubService::class.java)
                    .apply { action = HubService.ACTION_STOP_MIRROR })
            "input" -> InputService.instance?.handle(msg)   // desktop keyboard/mouse
        }
    }

    private fun requestProjection() {
        val act = reactContext.currentActivity ?: return
        val mpm = act.getSystemService(Activity.MEDIA_PROJECTION_SERVICE) as MediaProjectionManager
        act.startActivityForResult(mpm.createScreenCaptureIntent(), REQ_PROJECTION)
    }

    // ---- ActivityEventListener ----
    override fun onActivityResult(activity: Activity, requestCode: Int, resultCode: Int, data: Intent?) {
        if (requestCode == REQ_PROJECTION && resultCode == Activity.RESULT_OK && data != null) {
            val i = Intent(reactContext, HubService::class.java).apply {
                action = HubService.ACTION_MIRROR
                putExtra(HubService.EXTRA_CODE, resultCode)
                putExtra(HubService.EXTRA_DATA, data)
            }
            ContextCompat.startForegroundService(reactContext, i)
        } else if (requestCode == REQ_PICK_FILE && resultCode == Activity.RESULT_OK) {
            data?.data?.let { uri -> Thread { streamFile(uri) }.start() }
        }
    }

    /** file_offer (json) → binary 0x01 chunks → file_done (json). */
    private fun streamFile(uri: android.net.Uri) {
        val cr = reactContext.contentResolver
        var name = "file"
        var size = -1L
        try {
            cr.query(uri, null, null, null, null)?.use { c ->
                val ni = c.getColumnIndex(android.provider.OpenableColumns.DISPLAY_NAME)
                val si = c.getColumnIndex(android.provider.OpenableColumns.SIZE)
                if (c.moveToFirst()) {
                    if (ni >= 0) name = c.getString(ni) ?: name
                    if (si >= 0) size = c.getLong(si)
                }
            }
        } catch (_: Exception) {}

        val conn = Hub.connection ?: return
        val tid = "%08x".format((System.nanoTime() and 0xFFFFFFFFL).toInt())
        conn.send(JSONObject().apply {
            put("t", "file_offer"); put("transferId", tid); put("name", name); put("size", size)
        })
        try {
            val input: InputStream = cr.openInputStream(uri) ?: return
            input.use { ins ->
                val tidBytes = tid.toByteArray(Charsets.US_ASCII)   // 8 ascii bytes
                val buf = ByteArray(60 * 1024)
                while (true) {
                    val n = ins.read(buf)
                    if (n < 0) break
                    // payload = [8 ascii transferId][chunk]; channel 0x01 is prefixed by Connection
                    val payload = ByteArray(8 + n)
                    System.arraycopy(tidBytes, 0, payload, 0, 8)
                    System.arraycopy(buf, 0, payload, 8, n)
                    conn.sendBinary(0x01, payload)
                }
            }
        } catch (_: Exception) {}
        conn.send(JSONObject().apply { put("t", "file_done"); put("transferId", tid) })
    }

    override fun onNewIntent(intent: Intent) {}

    // Required no-ops so NativeEventEmitter doesn't warn.
    @ReactMethod fun addListener(eventName: String) {}
    @ReactMethod fun removeListeners(count: Int) {}

    companion object {
        private const val REQ_PROJECTION = 7001
        private const val REQ_PICK_FILE = 7002
    }
}
