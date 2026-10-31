package com.phonehubmobile

import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.Service
import android.content.Intent
import android.content.pm.ServiceInfo
import android.media.projection.MediaProjection
import android.media.projection.MediaProjectionManager
import android.os.Build
import android.os.IBinder
import androidx.core.app.NotificationCompat

/** Foreground service owning the screen-mirror encoder. Android 14 requires the
 *  mediaProjection FGS to be live BEFORE getMediaProjection(), so we
 *  startForeground() first. */
class HubService : Service() {
    private var encoder: ScreenEncoder? = null
    private var projection: MediaProjection? = null

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        ensureChannel()
        when (intent?.action) {
            ACTION_MIRROR -> {
                // Go foreground-as-mediaProjection ONLY with fresh consent in hand,
                // then start capture. Any failure must not crash the host app.
                try {
                    startInForeground()
                    startMirror(intent)
                } catch (e: Exception) {
                    stopSelf()
                }
            }
            ACTION_STOP_MIRROR -> { stopMirror(); stopForegroundCompat(); stopSelf() }
            else -> stopSelf()   // e.g. a null-intent restart — never auto-foreground
        }
        return START_NOT_STICKY
    }

    private fun stopForegroundCompat() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.N)
            stopForeground(STOP_FOREGROUND_REMOVE)
        else @Suppress("DEPRECATION") stopForeground(true)
    }

    private fun ensureChannel() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            val mgr = getSystemService(NotificationManager::class.java)
            if (mgr.getNotificationChannel(CHANNEL) == null) {
                mgr.createNotificationChannel(
                    NotificationChannel(CHANNEL, "PhoneHub link", NotificationManager.IMPORTANCE_LOW))
            }
        }
    }

    private fun startInForeground() {
        val n = NotificationCompat.Builder(this, CHANNEL)
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

        projection = getSystemService(MediaProjectionManager::class.java)
            .getMediaProjection(code, data)

        val m = resources.displayMetrics
        val scale = minOf(1f, 1080f / maxOf(m.widthPixels, m.heightPixels))
        val w = (m.widthPixels * scale).toInt() and 0xFFFE
        val h = (m.heightPixels * scale).toInt() and 0xFFFE

        encoder = ScreenEncoder(
            projection!!, w, h, m.densityDpi,
            intent.getIntExtra(EXTRA_BITRATE, 8_000_000),
        ) { Hub.connection?.sendBinary(0x02, it) }.also { it.start() }
    }

    private fun stopMirror() { encoder?.stop(); encoder = null; projection = null }

    override fun onDestroy() { stopMirror(); super.onDestroy() }
    override fun onBind(intent: Intent?): IBinder? = null

    companion object {
        const val CHANNEL = "hub"
        const val ACTION_MIRROR = "com.phonehubmobile.MIRROR"
        const val ACTION_STOP_MIRROR = "com.phonehubmobile.STOP_MIRROR"
        const val EXTRA_CODE = "code"
        const val EXTRA_DATA = "data"
        const val EXTRA_BITRATE = "bitrate"
    }
}
