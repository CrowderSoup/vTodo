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
        assertTrue(message.contains("SHA-1"))
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
