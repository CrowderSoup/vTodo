package com.crowdersoup.vtodo.work

import android.content.Context
import androidx.work.BackoffPolicy
import androidx.work.Constraints
import androidx.work.ExistingPeriodicWorkPolicy
import androidx.work.ExistingWorkPolicy
import androidx.work.ListenableWorker
import androidx.work.NetworkType
import androidx.work.OneTimeWorkRequestBuilder
import androidx.work.PeriodicWorkRequestBuilder
import androidx.work.WorkManager
import com.crowdersoup.vtodo.data.VtodoApiException
import java.util.concurrent.TimeUnit

object SyncScheduler {
    private const val PERIODIC = "vtodo-periodic-sync"
    private const val IMMEDIATE = "vtodo-immediate-sync"

    fun onSignedIn(context: Context) {
        val constraints = Constraints.Builder()
            .setRequiredNetworkType(NetworkType.CONNECTED)
            .build()
        val periodic = PeriodicWorkRequestBuilder<SyncWorker>(30, TimeUnit.MINUTES)
            .setConstraints(constraints)
            .setBackoffCriteria(BackoffPolicy.EXPONENTIAL, 30, TimeUnit.SECONDS)
            .build()
        WorkManager.getInstance(context).enqueueUniquePeriodicWork(
            PERIODIC,
            ExistingPeriodicWorkPolicy.UPDATE,
            periodic,
        )
        enqueueSoon(context)
    }

    fun enqueueSoon(context: Context) {
        val request = OneTimeWorkRequestBuilder<SyncWorker>()
            .setConstraints(
                Constraints.Builder().setRequiredNetworkType(NetworkType.CONNECTED).build(),
            )
            .build()
        WorkManager.getInstance(context).enqueueUniqueWork(
            IMMEDIATE,
            ExistingWorkPolicy.REPLACE,
            request,
        )
    }

    fun cancel(context: Context) {
        val work = WorkManager.getInstance(context)
        work.cancelUniqueWork(PERIODIC)
        work.cancelUniqueWork(IMMEDIATE)
    }
}

internal fun workerResult(outcome: Result<*>): ListenableWorker.Result {
    if (outcome.isSuccess) return ListenableWorker.Result.success()
    val error = outcome.exceptionOrNull()
    if (error is VtodoApiException && (error.httpCode == 401 || error.httpCode == 403)) {
        return ListenableWorker.Result.failure()
    }
    return ListenableWorker.Result.retry()
}
