package `in`.devaprakash.phonehub

import `in`.devaprakash.phonehub.net.Connection

/** Process-wide handles shared between the Activity and the foreground service. */
object Hub {
    @Volatile var connection: Connection? = null
}
