package `in`.devaprakash.phonehub.mirror

import android.hardware.display.DisplayManager
import android.hardware.display.VirtualDisplay
import android.media.MediaCodec
import android.media.MediaCodecInfo
import android.media.MediaFormat
import android.media.projection.MediaProjection
import android.view.Surface
import java.nio.ByteBuffer

/**
 * Captures the screen via MediaProjection, encodes H.264 (Annex-B byte stream)
 * with MediaCodec, and hands each access unit to [sink] as `[flags][AU bytes]`
 * (flags bit0 = keyframe) — exactly what the desktop's appsrc expects on
 * binary channel 0x02.
 */
class ScreenEncoder(
    private val projection: MediaProjection,
    private val width: Int,
    private val height: Int,
    private val dpi: Int,
    private val bitrate: Int,
    private val sink: (ByteArray) -> Unit,
) {
    private var codec: MediaCodec? = null
    private var surface: Surface? = null
    private var display: VirtualDisplay? = null
    @Volatile private var running = false
    private var drainThread: Thread? = null

    fun start() {
        val fmt = MediaFormat.createVideoFormat("video/avc", width, height).apply {
            setInteger(MediaFormat.KEY_COLOR_FORMAT,
                MediaCodecInfo.CodecCapabilities.COLOR_FormatSurface)
            setInteger(MediaFormat.KEY_BIT_RATE, bitrate)
            setInteger(MediaFormat.KEY_FRAME_RATE, 30)
            setInteger(MediaFormat.KEY_I_FRAME_INTERVAL, 2)
        }
        codec = MediaCodec.createEncoderByType("video/avc").apply {
            configure(fmt, null, null, MediaCodec.CONFIGURE_FLAG_ENCODE)
            surface = createInputSurface()
            start()
        }
        display = projection.createVirtualDisplay(
            "phonehub", width, height, dpi,
            DisplayManager.VIRTUAL_DISPLAY_FLAG_AUTO_MIRROR,
            surface, null, null,
        )
        running = true
        drainThread = Thread { drain() }.also { it.start() }
    }

    private fun drain() {
        val codec = codec ?: return
        val info = MediaCodec.BufferInfo()
        while (running) {
            val idx = codec.dequeueOutputBuffer(info, 10_000)
            if (idx < 0) continue
            val buf: ByteBuffer = codec.getOutputBuffer(idx) ?: continue
            buf.position(info.offset)
            buf.limit(info.offset + info.size)
            val au = ByteArray(info.size)
            buf.get(au)
            // codec config (SPS/PPS) and keyframes both flagged so the decoder
            // can start mid-stream.
            val isKey = (info.flags and MediaCodec.BUFFER_FLAG_KEY_FRAME) != 0 ||
                (info.flags and MediaCodec.BUFFER_FLAG_CODEC_CONFIG) != 0
            val out = ByteArray(au.size + 1)
            out[0] = if (isKey) 1 else 0
            System.arraycopy(au, 0, out, 1, au.size)
            sink(out)
            codec.releaseOutputBuffer(idx, false)
        }
    }

    fun stop() {
        running = false
        try { drainThread?.join(500) } catch (_: Exception) {}
        try { display?.release() } catch (_: Exception) {}
        try { codec?.stop(); codec?.release() } catch (_: Exception) {}
        try { surface?.release() } catch (_: Exception) {}
        try { projection.stop() } catch (_: Exception) {}
        codec = null; display = null; surface = null
    }
}
