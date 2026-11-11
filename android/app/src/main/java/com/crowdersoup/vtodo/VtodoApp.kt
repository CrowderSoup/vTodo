package com.crowdersoup.vtodo

import android.app.Application
import android.os.Build
import androidx.room.Room
import androidx.room.migration.Migration
import androidx.sqlite.db.SupportSQLiteDatabase
import com.crowdersoup.vtodo.data.SessionStore
import com.crowdersoup.vtodo.data.VtodoApi
import com.crowdersoup.vtodo.data.VtodoDatabase
import com.crowdersoup.vtodo.data.VtodoRepository
import com.crowdersoup.vtodo.widget.refreshTodayWidget
import com.crowdersoup.vtodo.work.SyncScheduler
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.launch

private val MIGRATION_1_2 = object : Migration(1, 2) {
    override fun migrate(db: SupportSQLiteDatabase) {
        db.execSQL("ALTER TABLE tasks ADD COLUMN notes TEXT NOT NULL DEFAULT ''")
        db.execSQL("ALTER TABLE statuses ADD COLUMN name TEXT NOT NULL DEFAULT ''")
    }
}

private val MIGRATION_2_3 = object : Migration(2, 3) {
    override fun migrate(db: SupportSQLiteDatabase) {
        db.execSQL("ALTER TABLE tasks ADD COLUMN tags TEXT NOT NULL DEFAULT '[]'")
        db.execSQL("ALTER TABLE statuses ADD COLUMN color TEXT NOT NULL DEFAULT ''")
    }
}

private val MIGRATION_3_4 = object : Migration(3, 4) {
    override fun migrate(db: SupportSQLiteDatabase) {
        db.execSQL("ALTER TABLE tasks ADD COLUMN recurrenceDays INTEGER")
        db.execSQL("ALTER TABLE tasks ADD COLUMN recurrenceFrom TEXT")
    }
}

private val MIGRATION_4_5 = object : Migration(4, 5) {
    override fun migrate(db: SupportSQLiteDatabase) {
        // Existing rows are all from the personal workspace; 0 stands for it
        // until the next sync fills in the real id.
        db.execSQL("ALTER TABLE tasks ADD COLUMN workspaceId INTEGER NOT NULL DEFAULT 0")
        db.execSQL("ALTER TABLE tasks ADD COLUMN workspaceName TEXT NOT NULL DEFAULT ''")
        // Slugs repeat across workspaces, so the key becomes (workspaceId, slug).
        db.execSQL(
            "CREATE TABLE statuses_new (" +
                "slug TEXT NOT NULL, id INTEGER NOT NULL, name TEXT NOT NULL, " +
                "sortOrder INTEGER NOT NULL, isDone INTEGER NOT NULL, color TEXT NOT NULL, " +
                "workspaceId INTEGER NOT NULL, PRIMARY KEY(workspaceId, slug))",
        )
        db.execSQL(
            "INSERT INTO statuses_new (slug, id, name, sortOrder, isDone, color, workspaceId) " +
                "SELECT slug, id, name, sortOrder, isDone, color, 0 FROM statuses",
        )
        db.execSQL("DROP TABLE statuses")
        db.execSQL("ALTER TABLE statuses_new RENAME TO statuses")
    }
}

class AppGraph(context: Application) {
    val sessionStore = SessionStore(context)
    val database: VtodoDatabase = Room.databaseBuilder(
        context,
        VtodoDatabase::class.java,
        "vtodo.db",
    ).addMigrations(MIGRATION_1_2, MIGRATION_2_3, MIGRATION_3_4, MIGRATION_4_5).build()
    val repository = VtodoRepository(
        database,
        VtodoApi(),
        sessionStore,
        deviceName(),
        requestSync = { SyncScheduler.enqueueSoon(context) },
    )
}

private fun deviceName(): String {
    val maker = Build.MANUFACTURER.orEmpty().replaceFirstChar { it.uppercase() }
    val model = Build.MODEL.orEmpty()
    return if (model.startsWith(maker, ignoreCase = true)) model else "$maker $model".trim()
}

class VtodoApp : Application() {
    lateinit var graph: AppGraph
        private set

    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Default)

    override fun onCreate() {
        super.onCreate()
        graph = AppGraph(this)
        if (graph.sessionStore.current() != null) {
            SyncScheduler.onSignedIn(this)
            scope.launch { refreshTodayWidget(this@VtodoApp) }
        }
    }
}
