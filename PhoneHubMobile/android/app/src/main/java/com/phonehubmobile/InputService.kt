package com.phonehubmobile

import android.accessibilityservice.AccessibilityService
import android.accessibilityservice.GestureDescription
import android.graphics.Path
import android.os.Bundle
import android.os.SystemClock
import android.view.accessibility.AccessibilityEvent
import android.view.accessibility.AccessibilityNodeInfo
import org.json.JSONObject
import kotlin.math.hypot

/**
 * Lets the desktop drive the phone with mouse + keyboard. Gestures (tap / swipe
 * / scroll) are injected with dispatchGesture; navigation keys use global
 * actions; typing edits the focused text field. The user enables this once under
 * Settings → Accessibility → PhoneHub Control.
 *
 * Desktop → phone control messages (see docs/PROTOCOL.md), all {"t":"input", ...}:
 *   {kind:"touch", action:"down"|"up", x, y}   x,y normalised 0..1
 *   {kind:"swipe", dx, dy}                      wheel scroll, fractions of screen
 *   {kind:"key",   key:"BACK"|"HOME"|"RECENTS"|"NOTIFICATIONS"|"ENTER"|"DEL"}
 *   {kind:"text",  text:"..."}                  append to the focused field
 */
class InputService : AccessibilityService() {

    override fun onServiceConnected() { instance = this }
    override fun onDestroy() { if (instance === this) instance = null; super.onDestroy() }
    override fun onAccessibilityEvent(event: AccessibilityEvent?) {}
    override fun onInterrupt() {}

    fun handle(msg: JSONObject) {
        when (msg.optString("kind")) {
            "touch" -> touch(msg)
            "swipe" -> swipe(msg)
            "key" -> key(msg.optString("key"))
            "text" -> typeText(msg.optString("text"))
        }
    }

    // ---- pointer ----
    private fun screen(): Pair<Int, Int> {
        val dm = resources.displayMetrics
        return dm.widthPixels to dm.heightPixels
    }

    private var downX = 0f
    private var downY = 0f
    private var downT = 0L

    private fun touch(m: JSONObject) {
        val (w, h) = screen()
        val x = (m.optDouble("x", 0.0) * w).toFloat().coerceIn(0f, w - 1f)
        val y = (m.optDouble("y", 0.0) * h).toFloat().coerceIn(0f, h - 1f)
        when (m.optString("action")) {
            "down" -> { downX = x; downY = y; downT = SystemClock.uptimeMillis() }
            "up" -> {
                val dist = hypot((x - downX).toDouble(), (y - downY).toDouble())
                val path = Path().apply {
                    moveTo(downX, downY)
                    if (dist > 12) lineTo(x, y) else lineTo(downX + 1f, downY + 1f)
                }
                // tap = quick; drag = honour how long the button was held (so a
                // slow drag scrolls instead of flinging).
                val held = (SystemClock.uptimeMillis() - downT).coerceIn(1, 3000)
                val dur = if (dist > 12) held else 40L
                gesture(path, dur)
            }
        }
    }

    private fun swipe(m: JSONObject) {
        val (w, h) = screen()
        val cx = w / 2f
        val cy = h / 2f
        val dx = (m.optDouble("dx", 0.0) * w).toFloat()
        val dy = (m.optDouble("dy", 0.0) * h).toFloat()
        val path = Path().apply { moveTo(cx, cy); lineTo(cx - dx, cy - dy) }
        gesture(path, 120)
    }

    private fun gesture(path: Path, durationMs: Long) {
        try {
            val g = GestureDescription.Builder()
                .addStroke(GestureDescription.StrokeDescription(path, 0, durationMs))
                .build()
            dispatchGesture(g, null, null)
        } catch (_: Exception) {}
    }

    // ---- keys ----
    private fun key(k: String) {
        when (k.uppercase()) {
            "BACK" -> performGlobalAction(GLOBAL_ACTION_BACK)
            "HOME" -> performGlobalAction(GLOBAL_ACTION_HOME)
            "RECENTS", "APP_SWITCH" -> performGlobalAction(GLOBAL_ACTION_RECENTS)
            "NOTIFICATIONS" -> performGlobalAction(GLOBAL_ACTION_NOTIFICATIONS)
            "ENTER" -> editFocused { node, cur -> setText(node, cur + "\n") }
            "DEL", "BACKSPACE" -> editFocused { node, cur -> if (cur.isNotEmpty()) setText(node, cur.dropLast(1)) }
        }
    }

    private fun typeText(s: String) {
        if (s.isEmpty()) return
        editFocused { node, cur -> setText(node, cur + s) }
    }

    private inline fun editFocused(block: (AccessibilityNodeInfo, String) -> Unit) {
        val node = findFocus(AccessibilityNodeInfo.FOCUS_INPUT) ?: return
        if (!node.isEditable) return
        block(node, node.text?.toString().orEmpty())
    }

    private fun setText(node: AccessibilityNodeInfo, text: String) {
        val args = Bundle().apply {
            putCharSequence(AccessibilityNodeInfo.ACTION_ARGUMENT_SET_TEXT_CHARSEQUENCE, text)
        }
        node.performAction(AccessibilityNodeInfo.ACTION_SET_TEXT, args)
        // keep the caret at the end
        node.performAction(
            AccessibilityNodeInfo.ACTION_SET_SELECTION,
            Bundle().apply {
                putInt(AccessibilityNodeInfo.ACTION_ARGUMENT_SELECTION_START_INT, text.length)
                putInt(AccessibilityNodeInfo.ACTION_ARGUMENT_SELECTION_END_INT, text.length)
            },
        )
    }

    companion object {
        @Volatile var instance: InputService? = null
    }
}
