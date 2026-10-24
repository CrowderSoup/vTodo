package com.crowdersoup.vtodo

import com.crowdersoup.vtodo.data.googleSignInFailureMessage
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class GoogleSignInFailureTest {
    @Test
    fun reauthFailedPointsAtTheSigningCertificate() {
        val message = googleSignInFailureMessage("[16] Account reauth failed.")
        assertTrue(message.contains("com.crowdersoup.vtodo"))
        assertTrue(message.contains("BD:FC:88:8A:8B:19:D2:D1:59:75:6A:31:37:CC:49:81:1E:9B:A6:8F"))
    }

    @Test
    fun hiddenCancellationBecomesAVisibleRetry() {
        assertEquals(
            "Google closed the sign-in before it finished. Try again, and tap your account once.",
            googleSignInFailureMessage("User cancelled the selector"),
        )
        assertEquals(
            "Google closed the sign-in before it finished. Try again, and tap your account once.",
            googleSignInFailureMessage("  "),
        )
    }

    @Test
    fun otherFailuresKeepTheDetail() {
        assertEquals(
            "No Google account is available on this phone.",
            googleSignInFailureMessage("No Google account is available on this phone."),
        )
    }
}
