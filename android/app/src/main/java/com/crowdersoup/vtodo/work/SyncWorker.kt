package com.crowdersoup.vtodo.work

import android.content.Context
import androidx.work.CoroutineWorker
import androidx.work.WorkerParameters
import com.crowdersoup.vtodo.VtodoApp
import com.crowdersoup.vtodo.widget.refreshTodayWidget

class SyncWorker(context: Context, params: WorkerParameters) : CoroutineWorker(context, params) {
    override suspend fun doWork(): Result {
        val graph = (applicationContext as VtodoApp).graph
        if (graph.sessionStore.current() == null) {
            // Signed out, possibly by a 401 in the last run. Retrying would
            // only back off and try again forever.
            SyncScheduler.cancel(applicationContext)
            refreshTodayWidget(applicationContext)
            return Result.success()
        }
        val outcome = graph.repository.sync()
        refreshTodayWidget(applicationContext)
        return workerResult(outcome)
    }
}
