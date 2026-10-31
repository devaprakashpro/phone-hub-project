package `in`.devaprakash.phonehub.net

import android.content.Context
import android.os.Build
import okhttp3.*
import okio.ByteString
import org.json.JSONObject
import java.util.concurrent.TimeUnit

/**
 * The single WebSocket link to the PhoneHub desktop, speaking docs/PROTOCOL.md.
 * Handles the pairing handshake; feature handlers register a listener.
 */
class Connection(
    private val ctx: Context,
    private val onState: (State) -> Unit,
    private val onControl: (JSONObject) -> Unit,
    private val needPin: () -> Unit,
) {
    enum class State { DISCONNECTED, CONNECTING, NEED_PIN, PAIRED, READY }

    private val client = OkHttpClient.Builder()
        .pingInterval(20, TimeUnit.SECONDS)
        .readTimeout(0, TimeUnit.MILLISECONDS)
        .build()

    private var ws: WebSocket? = null
    private val prefs = ctx.getSharedPreferences("phonehub", Context.MODE_PRIVATE)
    private val deviceId get() = prefs.getString("deviceId", null)
        ?: java.util.UUID.randomUUID().toString().also { prefs.edit().putString("deviceId", it).apply() }

    /** Connect to ws://host:8766. */
    fun connect(host: String, port: Int = 8766) {
        onState(State.CONNECTING)
        val req = Request.Builder().url("ws://$host:$port").build()
        ws = client.newWebSocket(req, object : WebSocketListener() {
            override fun onOpen(webSocket: WebSocket, response: Response) {
                send(JSONObject().apply {
                    put("t", "hello")
                    put("deviceId", deviceId)
                    put("name", "${Build.MANUFACTURER} ${Build.MODEL}")
                    prefs.getString("token", null)?.let { put("token", it) }
                })
            }

            override fun onMessage(webSocket: WebSocket, text: String) {
                val msg = JSONObject(text)
                when (msg.optString("t")) {
                    "need_pin" -> { onState(State.NEED_PIN); needPin() }
                    "paired" -> {
                        prefs.edit().putString("token", msg.optString("token")).apply()
                        onState(State.PAIRED)
                    }
                    "auth_fail" -> { onState(State.NEED_PIN); needPin() }
                    "ready" -> onState(State.READY)
                    else -> onControl(msg)
                }
            }

            override fun onMessage(webSocket: WebSocket, bytes: ByteString) {
                // binary in: desktop->phone file pushes (channel 0x01). Phase 2.
            }

            override fun onFailure(webSocket: WebSocket, t: Throwable, r: Response?) {
                onState(State.DISCONNECTED)
            }

            override fun onClosed(webSocket: WebSocket, code: Int, reason: String) {
                onState(State.DISCONNECTED)
            }
        })
    }

    fun sendPin(pin: String) = send(JSONObject().apply { put("t", "auth"); put("pin", pin) })

    fun send(obj: JSONObject) { ws?.send(obj.toString()) }

    /** Binary send with a 1-byte channel prefix (see PROTOCOL.md). */
    fun sendBinary(channel: Int, payload: ByteArray) {
        val buf = ByteArray(payload.size + 1)
        buf[0] = channel.toByte()
        System.arraycopy(payload, 0, buf, 1, payload.size)
        ws?.send(ByteString.of(*buf))
    }

    fun close() { ws?.close(1000, "bye"); ws = null }
}
