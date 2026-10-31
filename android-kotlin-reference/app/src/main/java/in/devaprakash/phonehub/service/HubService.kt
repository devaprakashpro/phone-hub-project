package `in`.devaprakash.phonehub.service

import android.app.Service
import android.content.Intent
import android.content.pm.ServiceInfo
import android.media.projection.MediaProjection
import android.media.projection.MediaProjectionManager
import android.os.Build
import android.os.IBinder
import androidx.core.app.NotificationCompat
import `in`.devaprakash.phonehub.Hub
import `in`.devaprakash.phonehub.PhoneHubApp
import `in`.devaprakash.phonehub.mirror.ScreenEncoder

/**
 * Foreground service owning the live link and the screen-mirror encoder.
 * Android 14 requires the mediaProjection foreground service to be running
 * BEFORE MediaProjectionManager.getMediaProjection(), so we startForeground()
 * first and create the projection here.
 */
class HubService : Service() {
    private var encoder: ScreenEncoder? = null
    private var projection: MediaProjection? = null

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        startInForeground()
        when (intent?.action) {
            ACTION_MIRROR -> startMirror(intent)
            ACTION_STOP_MIRROR -> stopMirror()
        }
        return START_STICKY
    }

    private fun startInForeground() {
        val n = NotificationCompat.Builder(this, PhoneHubApp.CHANNEL)
            .setContentTitle("PhoneHub")
            .setContentText("Connected to your laptop")
            .setSmallIcon(android.R.drawable.stat_sys_data_bluetooth)
            .setOngoing(true)
            .build()
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            startForeground(1, n, ServiceInfo.FOREGROUND_SERVICE_TYPE_MEDIA_PROJECTION)
        } else {
            startForeground(1, n)
        }
    }

    private fun startMirror(intent: Intent) {
        val code = intent.getIntExtra(EXTRA_CODE, 0)
        val data: Intent? =
            if (Build.VERSION.SDK_INT >= 33) intent.getParcelableExtra(EXTRA_DATA, Intent::class.java)
            else @Suppress("DEPRECATION") intent.getParcelableExtra(EXTRA_DATA)
        if (data == null) return

        val mpm = getSystemService(MediaProjectionManager::class.java)
        projection = mpm.getMediaProjection(code, data)

        val m = resources.displayMetrics
        // cap long side to ~1080 to keep bandwidth sane, preserve aspect
        val scale = minOf(1f, 1080f / maxOf(m.widthPixels, m.heightPixels))
        val w = (m.widthPixels * scale).toInt() and 0xFFFE   // even dims for H.264
        val h = (m.heightPixels * scale).toInt() and 0xFFFE

        encoder = ScreenEncoder(
            projection = projection!!,
            width = w, height = h, dpi = m.densityDpi,
            bitrate = intent.getIntExtra(EXTRA_BITRATE, 8_000_000),
            sink = { Hub.connection?.sendBinary(0x02, it) },
        ).also { it.start() }
    }

    private fun stopMirror() {
        encoder?.stop(); encoder = null
        projection = null
    }

    override fun onDestroy() {
        stopMirror()
        super.onDestroy()
    }

    override fun onBind(intent: Intent?): IBinder? = null

    companion object {
        const val ACTION_MIRROR = "in.devaprakash.phonehub.MIRROR"
        const val ACTION_STOP_MIRROR = "in.devaprakash.phonehub.STOP_MIRROR"
        const val EXTRA_CODE = "code"
        const val EXTRA_DATA = "data"
        const val EXTRA_BITRATE = "bitrate"
    }
}
