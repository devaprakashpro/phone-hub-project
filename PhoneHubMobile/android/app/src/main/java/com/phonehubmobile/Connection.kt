package com.phonehubmobile

import android.content.Context
import android.os.Build
import okhttp3.*
import okio.ByteString
import org.json.JSONObject
import java.util.UUID
import java.util.concurrent.Executors
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicBoolean

/** WebSocket link to the desktop (docs/PROTOCOL.md). Native-owned so video
 *  frames never cross the JS bridge.
 *
 *  Both transports are tried at once: the scanned LAN IP (Wi-Fi / Tailscale)
 *  and 127.0.0.1 (the USB `adb reverse 8766` tunnel). Whichever opens first
 *  wins, the loser is dropped. A short connect timeout means the unreachable
 *  side gives up fast instead of stalling the working one. */
class Connection(
    private val ctx: Context,
    private val onState: (String) -> Unit,
    private val onControl: (JSONObject) -> Unit,
    private val onNeedPin: () -> Unit,
    private val onBinary: (ByteArray) -> Unit = {},
) {
    private val client = OkHttpClient.Builder()
        .pingInterval(20, TimeUnit.SECONDS)
        .connectTimeout(4, TimeUnit.SECONDS)   // unreachable candidate fails fast
        .readTimeout(0, TimeUnit.MILLISECONDS)
        .build()

    @Volatile private var ws: WebSocket? = null
    private val pending = mutableListOf<WebSocket>()   // racers not yet settled
    private val settled = AtomicBoolean(false)
    private val closing = AtomicBoolean(false)
    private val prefs = ctx.getSharedPreferences("phonehub", Context.MODE_PRIVATE)
    private val deviceId: String
        get() = prefs.getString("deviceId", null) ?: UUID.randomUUID().toString()
            .also { prefs.edit().putString("deviceId", it).apply() }

    // --- ecosystem: keep the link alive ---
    @Volatile private var autoReconnect = false
    @Volatile private var lastHost = ""
    @Volatile private var lastPort = 8766
    @Volatile private var attempts = 0
    private val sched = Executors.newSingleThreadScheduledExecutor { r ->
        Thread(r, "phonehub-reconnect").apply { isDaemon = true }
    }

    /** User-initiated connect. Remembers the laptop and auto-reconnects on drops. */
    fun connect(host: String, port: Int) {
        lastHost = host
        lastPort = port
        prefs.edit().putString("lastHost", host).putInt("lastPort", port).apply()
        autoReconnect = true
        attempts = 0
        dial(host, port)
    }

    /** Reconnect to the laptop remembered from a previous pairing (app launch). */
    fun reconnectSaved(): Boolean {
        val host = prefs.getString("lastHost", null) ?: return false
        connect(host, prefs.getInt("lastPort", 8766))
        return true
    }

    private fun dial(host: String, port: Int) {
        dropSockets()
        closing.set(false)
        settled.set(false)
        onState("CONNECTING")
        val candidates = linkedSetOf(host)
        if (host != "127.0.0.1" && host != "localhost") candidates.add("127.0.0.1")
        synchronized(pending) {
            candidates.forEach { h -> pending.add(openRacer(h, port)) }
        }
    }

    /** Schedule a reconnect with capped exponential backoff (network blip,
     *  laptop asleep, etc.). Keeps the ecosystem link self-healing. */
    private fun scheduleReconnect() {
        if (!autoReconnect || closing.get()) return
        attempts++
        val delay = minOf(30L, (1L shl minOf(attempts, 5)))   // 2,4,8,16,30,30…s
        sched.schedule({
            if (autoReconnect && !closing.get() && ws == null) dial(lastHost, lastPort)
        }, delay, TimeUnit.SECONDS)
    }

    private fun openRacer(host: String, port: Int): WebSocket {
        val req = Request.Builder().url("ws://$host:$port").build()
        return client.newWebSocket(req, object : WebSocketListener() {
            override fun onOpen(webSocket: WebSocket, response: Response) {
                // First racer to open wins; cancel the rest.
                if (!settled.compareAndSet(false, true)) {
                    webSocket.cancel()
                    return
                }
                ws = webSocket
                attempts = 0                       // healthy link → reset backoff
                synchronized(pending) {
                    pending.filter { it !== webSocket }.forEach { it.cancel() }
                    pending.clear()
                }
                send(JSONObject().apply {
                    put("t", "hello")
                    put("deviceId", deviceId)
                    put("name", "${Build.MANUFACTURER} ${Build.MODEL}")
                    prefs.getString("token", null)?.let { put("token", it) }
                })
            }

            override fun onMessage(webSocket: WebSocket, bytes: ByteString) {
                if (webSocket !== ws) return
                onBinary(bytes.toByteArray())     // incoming file chunks (laptop→phone)
            }

            override fun onMessage(webSocket: WebSocket, text: String) {
                if (webSocket !== ws) return
                val msg = JSONObject(text)
                when (msg.optString("t")) {
                    "need_pin" -> { onState("NEED_PIN"); onNeedPin() }
                    "paired" -> {
                        prefs.edit().putString("token", msg.optString("token")).apply()
                        onState("PAIRED")
                    }
                    "auth_fail" -> { onState("NEED_PIN"); onNeedPin() }
                    "ready" -> onState("READY")
                    else -> onControl(msg)
                }
            }

            override fun onFailure(webSocket: WebSocket, t: Throwable, r: Response?) {
                if (webSocket === ws) {                       // the live link dropped
                    ws = null
                    if (!closing.get()) { onState("DISCONNECTED"); scheduleReconnect() }
                    return
                }
                // A racer failed (e.g. unreachable LAN IP). Only report
                // DISCONNECTED (and retry) once every racer has given up and none won.
                var allDone = false
                synchronized(pending) {
                    pending.remove(webSocket)
                    allDone = pending.isEmpty()
                }
                if (allDone && !settled.get() && !closing.get()) {
                    onState("DISCONNECTED"); scheduleReconnect()
                }
            }

            override fun onClosed(webSocket: WebSocket, code: Int, reason: String) {
                if (webSocket === ws) {
                    ws = null
                    if (!closing.get()) { onState("DISCONNECTED"); scheduleReconnect() }
                }
            }
        })
    }

    fun sendPin(pin: String) = send(JSONObject().apply { put("t", "auth"); put("pin", pin) })
    fun send(obj: JSONObject) { ws?.send(obj.toString()) }

    fun sendBinary(channel: Int, payload: ByteArray) {
        val buf = ByteArray(payload.size + 1)
        buf[0] = channel.toByte()
        System.arraycopy(payload, 0, buf, 1, payload.size)
        ws?.send(ByteString.of(*buf))
    }

    /** Cancel sockets without disabling auto-reconnect (used between dials). */
    private fun dropSockets() {
        closing.set(true)
        synchronized(pending) {
            pending.forEach { it.cancel() }
            pending.clear()
        }
        ws?.close(1000, "bye")
        ws = null
    }

    /** User-initiated disconnect: stop reconnecting and tear down. */
    fun close() {
        autoReconnect = false
        dropSockets()
    }
}

/** Shared between the bridge module and the foreground service. */
object Hub {
    @Volatile var connection: Connection? = null
}
