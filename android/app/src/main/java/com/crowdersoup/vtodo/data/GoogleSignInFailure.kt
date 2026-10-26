package com.crowdersoup.vtodo.data

/**
 * Google reports several setup failures as a user cancellation, including a
 * rejected signing certificate. The sign-in screen has to say which one.
 */
internal fun googleSignInFailureMessage(raw: String?): String {
    val detail = raw?.trim().orEmpty()
    val lower = detail.lowercase()
    if (
        "account reauth failed" in lower ||
        "developer console" in lower ||
        "developer_error" in lower ||
        "[10]" in lower
    ) {
        return "Google rejected this app's signing certificate. The Android OAuth client " +
            "needs package com.crowdersoup.vtodo and the SHA-1 of the key this build " +
            "was signed with, in the same Google Cloud project as the website."
    }
    if (
        detail.isEmpty() ||
        "cancelled by user" in lower ||
        "canceled by user" in lower ||
        "user cancelled" in lower ||
        "user canceled" in lower ||
        "activity is cancelled" in lower ||
        "activity is canceled" in lower
    ) {
        return "Google closed the sign-in before it finished. Try again, and tap your account once."
    }
    return detail
}
