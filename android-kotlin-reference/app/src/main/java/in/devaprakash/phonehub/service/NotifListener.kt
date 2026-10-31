package `in`.devaprakash.phonehub.service

import android.service.notification.NotificationListenerService
import android.service.notification.StatusBarNotification

/**
 * Mirrors phone notifications to the desktop. The user must grant
 * "Notification access" in Settings (one-time). Phase 2 wires these into the
 * Connection as {"t":"notification", ...} control messages.
 */
class NotifListener : NotificationListenerService() {
    override fun onNotificationPosted(sbn: StatusBarNotification) {
        // TODO(phase 2): forward sbn.packageName + title/text to the desktop.
    }
    override fun onNotificationRemoved(sbn: StatusBarNotification) {
        // TODO(phase 2): send {"t":"notif_removed","id":sbn.key}.
    }
}
