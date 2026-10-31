package com.phonehubmobile

import android.app.Notification
import android.service.notification.NotificationListenerService
import android.service.notification.StatusBarNotification
import org.json.JSONObject

/**
 * Mirrors phone notifications to the desktop. The user grants "Notification
 * access" once in Settings (the app deep-links there). Each post becomes a
 * {"t":"notification", ...} control message; removals send {"t":"notif_removed"}.
 * The desktop already renders these in its Alerts tab.
 */
class NotifListener : NotificationListenerService() {

    override fun onListenerConnected() {
        instance = this
        // Replay whatever is already in the shade so a freshly-paired desktop
        // isn't empty until the next notification arrives.
        try {
            activeNotifications?.forEach { forward(it) }
        } catch (_: Exception) {}
    }

    override fun onListenerDisconnected() {
        if (instance === this) instance = null
    }

    override fun onNotificationPosted(sbn: StatusBarNotification) = forward(sbn)

    override fun onNotificationRemoved(sbn: StatusBarNotification) {
        Hub.connection?.send(JSONObject().apply {
            put("t", "notif_removed")
            put("id", sbn.key)
        })
    }

    private fun forward(sbn: StatusBarNotification) {
        val n = sbn.notification ?: return
        // Skip ongoing/group-summary noise (our own FGS, media transport bars…).
        if (n.flags and Notification.FLAG_ONGOING_EVENT != 0) return
        if (n.flags and Notification.FLAG_GROUP_SUMMARY != 0) return

        val ex = n.extras
        val title = ex.getCharSequence(Notification.EXTRA_TITLE)?.toString().orEmpty()
        val text = (ex.getCharSequence(Notification.EXTRA_TEXT)
            ?: ex.getCharSequence(Notification.EXTRA_BIG_TEXT))?.toString().orEmpty()
        if (title.isBlank() && text.isBlank()) return

        Hub.connection?.send(JSONObject().apply {
            put("t", "notification")
            put("id", sbn.key)
            put("app", appLabel(sbn.packageName))
            put("title", title)
            put("text", text)
            put("ts", sbn.postTime)
        })
    }

    private fun appLabel(pkg: String): String = try {
        val pm = packageManager
        pm.getApplicationLabel(pm.getApplicationInfo(pkg, 0)).toString()
    } catch (_: Exception) {
        pkg
    }

    companion object {
        @Volatile var instance: NotifListener? = null
    }
}
