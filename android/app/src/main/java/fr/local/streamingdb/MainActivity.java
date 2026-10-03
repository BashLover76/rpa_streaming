package fr.local.streamingdb;

import android.app.Activity;
import android.app.AlertDialog;
import android.content.Intent;
import android.content.SharedPreferences;
import android.content.res.Configuration;
import android.graphics.Bitmap;
import android.graphics.BitmapFactory;
import android.graphics.Color;
import android.graphics.Typeface;
import android.graphics.drawable.GradientDrawable;
import android.net.Uri;
import android.os.Bundle;
import android.text.Editable;
import android.text.TextWatcher;
import android.text.method.DigitsKeyListener;
import android.util.DisplayMetrics;
import android.view.Gravity;
import android.widget.Button;
import android.widget.CheckBox;
import android.widget.EditText;
import android.widget.HorizontalScrollView;
import android.widget.ImageView;
import android.widget.LinearLayout;
import android.widget.ProgressBar;
import android.widget.ScrollView;
import android.widget.ArrayAdapter;
import android.widget.Spinner;
import android.widget.TextView;
import android.widget.Toast;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.BufferedReader;
import java.io.File;
import java.io.FileOutputStream;
import java.io.InputStream;
import java.io.InputStreamReader;
import java.io.OutputStream;
import java.io.UnsupportedEncodingException;
import java.net.HttpURLConnection;
import java.net.URL;
import java.net.URLEncoder;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.security.MessageDigest;
import java.time.LocalDate;
import java.time.YearMonth;
import java.time.format.DateTimeFormatter;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.HashSet;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

public class MainActivity extends Activity {
    private static final int DEFAULT_PAGE_SIZE = 10;
    private static final String APP_VERSION = "1.0.0";

    private final ExecutorService executor = Executors.newFixedThreadPool(3);
    private final List<Screen> backStack = new ArrayList<>();
    private SharedPreferences prefs;
    private LinearLayout root;
    private LinearLayout tabs;
    private LinearLayout content;
    private EditText serverInput;
    private EditText searchInput;
    private ProgressBar progress;
    private TextView syncStatus;
    private EditText gridColumnsInput;
    private EditText maxRowsInput;
    private EditText syncAlertHoursInput;
    private CheckBox syncAlertEnabledInput;
    private CheckBox episodeAlertEnabledInput;
    private CheckBox hideEmptyCalendarDaysInput;
    private Screen currentScreen = Screen.titles("series", 0);
    private YearMonth calendarMonth = YearMonth.now();
    private int colorBg;
    private int colorPanel;
    private int colorPanelAlt;
    private int colorText;
    private int colorMuted;
    private int colorLine;
    private int colorAccent;
    private String sortMode = "recent";
    private String language = "fr";
    private String activeProfileKey = "";
    private boolean bootstrapRefreshInFlight = false;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        prefs = getSharedPreferences("streaming-db", MODE_PRIVATE);
        language = prefs.getString("language", "fr");
        activeProfileKey = prefs.getString("profile_key", "");
        configurePalette();
        buildLayout();
        navigate(Screen.titles("series", 0), false);
    }

    @Override
    public void onBackPressed() {
        if (!backStack.isEmpty()) {
            render(backStack.remove(backStack.size() - 1));
            return;
        }
        new AlertDialog.Builder(this)
                .setTitle("Quitter StreamPilot ?")
                .setMessage(tr("no_previous_screen"))
                .setNegativeButton(tr("stay"), null)
                .setPositiveButton(tr("quit"), (dialog, which) -> finish())
                .show();
    }

    private void configurePalette() {
        boolean dark = (getResources().getConfiguration().uiMode
                & Configuration.UI_MODE_NIGHT_MASK) == Configuration.UI_MODE_NIGHT_YES;
        colorBg = dark ? Color.rgb(16, 18, 20) : Color.rgb(246, 248, 251);
        colorPanel = dark ? Color.rgb(25, 29, 33) : Color.WHITE;
        colorPanelAlt = dark ? Color.rgb(32, 38, 43) : Color.rgb(239, 244, 249);
        colorText = dark ? Color.rgb(237, 241, 245) : Color.rgb(17, 24, 39);
        colorMuted = dark ? Color.rgb(154, 166, 178) : Color.rgb(75, 85, 99);
        colorLine = dark ? Color.rgb(48, 56, 65) : Color.rgb(209, 217, 226);
        colorAccent = Color.rgb(79, 179, 255);
    }

    private void buildLayout() {
        root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setPadding(dp(16), dp(18), dp(16), dp(16));
        root.setBackgroundColor(colorBg);
        root.addView(titleText("StreamPilot", 28));

        searchInput = new EditText(this);
        searchInput.setHint(tr("search_offline"));
        styleInput(searchInput);
        searchInput.addTextChangedListener(new TextWatcher() {
            @Override
            public void beforeTextChanged(CharSequence value, int start, int count, int after) {
            }

            @Override
            public void onTextChanged(CharSequence value, int start, int before, int count) {
                if (currentScreen != null && !"admin".equals(currentScreen.kind)) {
                    render(currentScreen.withPage(0));
                }
            }

            @Override
            public void afterTextChanged(Editable value) {
            }
        });
        root.addView(searchInput, matchWrap());

        tabs = new LinearLayout(this);
        tabs.setOrientation(LinearLayout.HORIZONTAL);
        tabs.setPadding(0, dp(6), 0, dp(6));
        addTab(R.drawable.ic_series, tr("series"), () -> navigate(Screen.titles("series", 0), true));
        addTab(R.drawable.ic_movie, tr("movies"), () -> navigate(Screen.titles("movie", 0), true));
        addTab(R.drawable.ic_resume, tr("resume"), () -> navigate(Screen.resume(0), true));
        addTab(R.drawable.ic_calendar, tr("calendar"), () -> navigate(Screen.calendar(calendarMonth), true));
        addTab(R.drawable.ic_admin, "Admin", () -> navigate(Screen.admin(), true));
        root.addView(tabs);

        progress = new ProgressBar(this);
        progress.setVisibility(ProgressBar.GONE);
        root.addView(progress);

        ScrollView scroll = new ScrollView(this);
        scroll.setClipToPadding(false);
        scroll.setPadding(0, 0, 0, dp(96));
        content = new LinearLayout(this);
        content.setOrientation(LinearLayout.VERTICAL);
        content.setPadding(0, 0, 0, dp(24));
        scroll.addView(content);
        root.addView(scroll, new LinearLayout.LayoutParams(-1, 0, 1));
        setContentView(root);
    }

    private void addTab(int iconRes, String description, Runnable action) {
        Button button = new Button(this);
        button.setText("");
        button.setContentDescription(description);
        button.setCompoundDrawablesWithIntrinsicBounds(0, iconRes, 0, 0);
        button.setCompoundDrawablePadding(0);
        button.setGravity(Gravity.CENTER);
        button.setMinHeight(dp(44));
        styleButton(button, false);
        button.setOnClickListener(v -> action.run());
        LinearLayout.LayoutParams params = new LinearLayout.LayoutParams(0, dp(48), 1);
        params.setMargins(dp(3), 0, dp(3), 0);
        tabs.addView(button, params);
    }

    private void navigate(Screen screen, boolean push) {
        if (push) backStack.add(currentScreen);
        render(screen);
    }

    private void render(Screen screen) {
        currentScreen = screen;
        content.removeAllViews();
        if ("detail".equals(screen.kind)) {
            renderDetail(screen.id);
        } else if ("calendar".equals(screen.kind)) {
            calendarMonth = screen.month;
            renderCalendar();
        } else if ("admin".equals(screen.kind)) {
            renderAdmin();
        } else if ("resume".equals(screen.kind)) {
            renderResume(screen.page);
        } else {
            renderTitles(screen.type, screen.page);
        }
    }

    private void renderTitles(String type, int page) {
        JSONObject payload = cachedJson(cacheKeyForTitles(type));
        if (payload == null) {
            addMessage(tr("no_offline_data"));
            return;
        }
        List<JSONObject> filtered = filteredTitles(payload.optJSONArray("items"));
        sortTitles(filtered);
        addSection(("movie".equals(type) ? tr("movies") : tr("series")) + " · " + filtered.size() + " " + tr("titles"));
        addSortFilter();
        int pageSize = pageSize();
        int totalPages = Math.max(1, (filtered.size() + pageSize - 1) / pageSize);
        int safePage = Math.max(0, Math.min(page, totalPages - 1));
        int start = safePage * pageSize;
        int end = Math.min(filtered.size(), start + pageSize);
        int columns = gridColumns();
        for (int index = start; index < end; index += columns) {
            LinearLayout row = new LinearLayout(this);
            row.setOrientation(LinearLayout.HORIZONTAL);
            for (int column = 0; column < columns; column++) {
                int itemIndex = index + column;
                if (itemIndex < end) {
                    row.addView(posterTile(filtered.get(itemIndex)), new LinearLayout.LayoutParams(0, -2, 1));
                } else {
                    row.addView(new TextView(this), new LinearLayout.LayoutParams(0, -2, 1));
                }
            }
            content.addView(row);
        }
        addPagination(type, safePage, totalPages);
    }

    private List<JSONObject> filteredTitles(JSONArray items) {
        List<JSONObject> result = new ArrayList<>();
        String query = currentQuery();
        if (items == null) return result;
        for (int index = 0; index < items.length(); index++) {
            JSONObject item = items.optJSONObject(index);
            if (item != null && profileMatches(item) && titleMatches(item, query)) {
                result.add(item);
            }
        }
        return result;
    }

    private void renderResume(int page) {
        List<JSONObject> resumable = resumableTitles();
        sortTitles(resumable);
        addSection(tr("resume") + " · " + resumable.size() + " " + tr("titles"));
        addSortFilter();
        if (resumable.isEmpty()) {
            addMessage(tr("resume_empty"));
            return;
        }
        int pageSize = pageSize();
        int totalPages = Math.max(1, (resumable.size() + pageSize - 1) / pageSize);
        int safePage = Math.max(0, Math.min(page, totalPages - 1));
        int start = safePage * pageSize;
        int end = Math.min(resumable.size(), start + pageSize);
        int columns = gridColumns();
        for (int index = start; index < end; index += columns) {
            LinearLayout row = new LinearLayout(this);
            row.setOrientation(LinearLayout.HORIZONTAL);
            for (int column = 0; column < columns; column++) {
                int itemIndex = index + column;
                if (itemIndex < end) {
                    row.addView(posterTile(resumable.get(itemIndex)), new LinearLayout.LayoutParams(0, -2, 1));
                } else {
                    row.addView(new TextView(this), new LinearLayout.LayoutParams(0, -2, 1));
                }
            }
            content.addView(row);
        }
        addResumePagination(safePage, totalPages);
    }

    private List<JSONObject> resumableTitles() {
        List<JSONObject> result = new ArrayList<>();
        addResumableFromCache(result, cachedJson(cacheKeyForTitles("series")));
        addResumableFromCache(result, cachedJson(cacheKeyForTitles("movie")));
        String query = currentQuery();
        if (query.isEmpty()) return result;
        List<JSONObject> filtered = new ArrayList<>();
        for (JSONObject item : result) {
            if (titleMatches(item, query)) filtered.add(item);
        }
        return filtered;
    }

    private void addResumableFromCache(List<JSONObject> target, JSONObject payload) {
        if (payload == null) return;
        JSONArray items = payload.optJSONArray("items");
        if (items == null) return;
        for (int index = 0; index < items.length(); index++) {
            JSONObject item = items.optJSONObject(index);
            if (item != null && isResumable(item)) target.add(item);
        }
    }

    private boolean isResumable(JSONObject item) {
        String type = item.optString("type");
        int watched = item.optInt("watched_count", 0);
        int total = item.optInt("episode_count", 0);
        if ("series".equals(type)) {
            if (total > 0) return watched > 0 && watched < total;
            return detailHasInProgressHistory(cachedJson(cacheKeyForDetail(item.optInt("id"))));
        }
        return detailHasInProgressHistory(cachedJson(cacheKeyForDetail(item.optInt("id"))));
    }

    private boolean detailHasInProgressHistory(JSONObject detail) {
        if (detail == null) return false;
        JSONArray history = detail.optJSONArray("history");
        if (history == null) return false;
        for (int index = 0; index < history.length(); index++) {
            JSONObject item = history.optJSONObject(index);
            if (item == null) continue;
            String status = item.optString("status", "");
            int progress = item.optInt("progress_percent", 0);
            if ("in_progress".equals(status) || "resume".equals(status)) return true;
            if (progress > 0 && progress < 95) return true;
        }
        return false;
    }

    private void sortTitles(List<JSONObject> items) {
        if ("title".equals(sortMode)) {
            items.sort(Comparator.comparing(item -> item.optString("title", "").toLowerCase()));
            return;
        }
        items.sort(Comparator.comparing((JSONObject item) -> sortableDate(item.optString("last_watched_at", ""))).reversed());
    }

    private String sortableDate(String value) {
        if (value == null) return "";
        String trimmed = value.trim();
        return trimmed.matches("\\d{4}-\\d{2}-\\d{2}.*") ? trimmed : "";
    }

    private void addSortFilter() {
        LinearLayout row = new LinearLayout(this);
        row.setOrientation(LinearLayout.HORIZONTAL);
        Button recent = button(tr("last_seen"), "recent".equals(sortMode));
        recent.setOnClickListener(v -> {
            sortMode = "recent";
            render(currentScreen);
        });
        row.addView(recent, new LinearLayout.LayoutParams(0, -2, 1));
        Button title = button(tr("title_az"), "title".equals(sortMode));
        title.setOnClickListener(v -> {
            sortMode = "title";
            render(currentScreen);
        });
        row.addView(title, new LinearLayout.LayoutParams(0, -2, 1));
        content.addView(row);
    }

    private LinearLayout posterTile(JSONObject item) {
        LinearLayout card = new LinearLayout(this);
        card.setOrientation(LinearLayout.VERTICAL);
        card.setGravity(Gravity.CENTER);
        card.setPadding(dp(5), dp(5), dp(5), dp(5));
        LinearLayout.LayoutParams params = new LinearLayout.LayoutParams(-1, -2);
        params.setMargins(dp(3), dp(6), dp(3), dp(2));
        card.setLayoutParams(params);
        card.setBackground(rounded(colorPanel, colorLine, 8));
        ImageView poster = posterView(tilePosterWidth(), Math.round(tilePosterWidth() * 1.5f));
        loadImage(poster, item.optString("poster_url"));
        card.addView(poster);
        card.setOnClickListener(v -> navigate(Screen.detail(item.optInt("id")), true));
        return card;
    }

    private void addPagination(String type, int page, int totalPages) {
        LinearLayout row = new LinearLayout(this);
        row.setOrientation(LinearLayout.HORIZONTAL);
        Button previous = button(tr("previous"), false);
        previous.setEnabled(page > 0);
        previous.setOnClickListener(v -> navigate(Screen.titles(type, page - 1), false));
        row.addView(previous, new LinearLayout.LayoutParams(0, -2, 1));
        TextView label = line(tr("page") + " " + (page + 1) + "/" + totalPages);
        label.setGravity(Gravity.CENTER);
        row.addView(label, new LinearLayout.LayoutParams(0, -2, 1));
        Button next = button(tr("next"), false);
        next.setEnabled(page + 1 < totalPages);
        next.setOnClickListener(v -> navigate(Screen.titles(type, page + 1), false));
        row.addView(next, new LinearLayout.LayoutParams(0, -2, 1));
        content.addView(row);
    }

    private void addResumePagination(int page, int totalPages) {
        LinearLayout row = new LinearLayout(this);
        row.setOrientation(LinearLayout.HORIZONTAL);
        Button previous = button(tr("previous"), false);
        previous.setEnabled(page > 0);
        previous.setOnClickListener(v -> navigate(Screen.resume(page - 1), false));
        row.addView(previous, new LinearLayout.LayoutParams(0, -2, 1));
        TextView label = line(tr("page") + " " + (page + 1) + "/" + totalPages);
        label.setGravity(Gravity.CENTER);
        row.addView(label, new LinearLayout.LayoutParams(0, -2, 1));
        Button next = button(tr("next"), false);
        next.setEnabled(page + 1 < totalPages);
        next.setOnClickListener(v -> navigate(Screen.resume(page + 1), false));
        row.addView(next, new LinearLayout.LayoutParams(0, -2, 1));
        content.addView(row);
    }

    private void renderDetail(int id) {
        JSONObject payload = cachedJson(cacheKeyForDetail(id));
        if (payload == null) {
            addMessage(tr("detail_unavailable"));
            return;
        }
        LinearLayout hero = card();
        ImageView poster = posterView(220, 330);
        loadImage(poster, payload.optString("poster_url"));
        hero.addView(poster);
        hero.addView(titleText(payload.optString("title"), 24));
        addPlatformBadges(hero, payload);
        addNullable(hero, payload.optString("synopsis"));
        JSONObject status = payload.optJSONObject("status");
        if (status != null) hero.addView(line(status.optString("label") + " · " + status.optString("detail")));
        Button open = button(tr("open_platform"), true);
        open.setOnClickListener(v -> openDeepLink(payload.optString("deep_link_url")));
        hero.addView(open);
        content.addView(hero);
        if (!"movie".equals(payload.optString("type"))) {
            addSection(tr("upcoming"));
            addEpisodeList(payload.optJSONArray("upcoming"), false);
        }
        addSection(tr("recent_history"));
        addEpisodeList(payload.optJSONArray("history"), true);
        addProfileProgress(payload.optJSONArray("profile_progress"));
    }

    private void addProfileProgress(JSONArray items) {
        if (items == null || items.length() == 0) return;
        addSection(tr("profile_progress"));
        for (int index = 0; index < items.length(); index++) {
            JSONObject item = items.optJSONObject(index);
            if (item == null) continue;
            LinearLayout row = card();
            String label = item.optString("profile_label", item.optString("profile_key", ""));
            String watched = item.optInt("watched_episodes", 0) + " " + tr("episodes_seen");
            String date = item.optString("last_watched_at", "");
            row.addView(titleText(label, 16));
            row.addView(line(date.isEmpty() ? watched : watched + " · " + date));
            content.addView(row);
        }
    }

    private void addEpisodeList(JSONArray items, boolean watched) {
        if (items == null || items.length() == 0) {
            addMessage(tr("no_data"));
            return;
        }
        for (int index = 0; index < Math.min(items.length(), 30); index++) {
            JSONObject item = items.optJSONObject(index);
            if (item == null) continue;
            LinearLayout row = card();
            String date = watched ? item.optString("watched_at", "?") : item.optString("release_date", "?");
            String episode = episodeCode(item);
            row.addView(titleText(episode.isEmpty() ? date : date + " · " + episode, 16));
            row.addView(line(item.optString("episode_title")));
            row.setOnClickListener(v -> openDeepLink(item.optString("deep_link_url")));
            content.addView(row);
        }
    }

    private void renderCalendar() {
        JSONObject payload = cachedJson(cacheKeyForCalendar(calendarMonth));
        if (payload == null) payload = cachedJson("calendar");
        if (payload == null) {
            addMessage(tr("calendar_unavailable"));
            return;
        }
        LinearLayout nav = new LinearLayout(this);
        nav.setOrientation(LinearLayout.HORIZONTAL);
        Button prev = button("<", false);
        prev.setOnClickListener(v -> navigate(Screen.calendar(calendarMonth.minusMonths(1)), false));
        nav.addView(prev, new LinearLayout.LayoutParams(0, -2, 1));
        TextView title = titleText(calendarMonth.toString(), 22);
        title.setGravity(Gravity.CENTER);
        nav.addView(title, new LinearLayout.LayoutParams(0, -2, 3));
        Button next = button(">", false);
        next.setOnClickListener(v -> navigate(Screen.calendar(calendarMonth.plusMonths(1)), false));
        nav.addView(next, new LinearLayout.LayoutParams(0, -2, 1));
        content.addView(nav);

        JSONArray episodes = payload.optJSONArray("episodes");
        boolean hideEmptyDays = prefs.getBoolean("hide_empty_calendar_days", false);
        for (int day = 1; day <= calendarMonth.lengthOfMonth(); day++) {
            LocalDate date = calendarMonth.atDay(day);
            LinearLayout dayCard = card();
            dayCard.addView(titleText(date.format(DateTimeFormatter.ofPattern("dd/MM")), 17));
            int count = 0;
            HorizontalScrollView carousel = new HorizontalScrollView(this);
            LinearLayout carouselRow = new LinearLayout(this);
            carouselRow.setOrientation(LinearLayout.HORIZONTAL);
            if (episodes != null) {
                for (int index = 0; index < episodes.length(); index++) {
                    JSONObject item = episodes.optJSONObject(index);
                    if (item == null || !date.toString().equals(item.optString("release_date"))) continue;
                    if (!titleMatches(item, currentQuery())) continue;
                    carouselRow.addView(calendarPosterTile(item));
                    count++;
                }
            }
            if (count > 0 || (currentQuery().isEmpty() && !hideEmptyDays)) {
                if (count == 0) dayCard.addView(line("Aucune sortie connue"));
                if (count > 0) {
                    carousel.addView(carouselRow);
                    dayCard.addView(carousel);
                }
                content.addView(dayCard);
            }
        }
    }

    private void renderAdmin() {
        addSection(tr("general"));
        addSection(tr("server_connection"));
        serverInput = new EditText(this);
        serverInput.setText(prefs.getString("server_url", "http://192.168.1.170:5000"));
        serverInput.setHint("http://IP_DU_SERVEUR:5000");
        styleInput(serverInput);
        content.addView(serverInput, matchWrap());
        Button save = button(tr("save"), false);
        save.setOnClickListener(v -> prefs.edit().putString("server_url", normalizedServerUrl()).apply());
        content.addView(save);
        Button sync = button(tr("sync_now"), true);
        sync.setOnClickListener(v -> synchronizeOfflineDatabase());
        content.addView(sync);
        syncStatus = line(lastSyncLabel());
        content.addView(syncStatus);
        addLanguageSettings();
        addAdminSettings();
        addSection(tr("profile"));
        addProfileSettings();
        addCreateMetaProfileSettings();
        addMetaProfileSettings();
        addPlatformProfileSettings();
        addSection(tr("rpa_restart"));
        addRpaControls();
        addSection(tr("offline_kpis"));
        addAdminKpis();
        addIngestionStatuses();
        addSection(tr("alerts"));
        addSyncAlertSettings();
        addDebugLog();
        addMessage(tr("app_version") + ": " + APP_VERSION);
    }

    private void addAdminSettings() {
        LinearLayout settings = card();
        settings.addView(line(tr("display_help")));
        gridColumnsInput = numberInput(String.valueOf(gridColumns()), tr("columns_hint"));
        maxRowsInput = numberInput(String.valueOf(maxRowsPerPage()), tr("rows_hint"));
        settings.addView(gridColumnsInput);
        settings.addView(maxRowsInput);
        Button save = button(tr("save_display"), false);
        save.setOnClickListener(v -> {
            prefs.edit()
                    .putInt("grid_columns", clamp(parseInt(gridColumnsInput.getText().toString(), 4), 1, 4))
                    .putInt("max_rows_per_page", clamp(parseInt(maxRowsInput.getText().toString(), 4), 1, 20))
                    .apply();
            Toast.makeText(this, tr("display_saved"), Toast.LENGTH_SHORT).show();
        });
        settings.addView(save);
        content.addView(settings);
    }

    private void addLanguageSettings() {
        LinearLayout row = card();
        row.setOrientation(LinearLayout.HORIZONTAL);
        addLanguageButton(row, "fr", "🇫🇷");
        addLanguageButton(row, "en", "🇬🇧");
        addLanguageButton(row, "es", "🇪🇸");
        content.addView(row);
    }

    private void addLanguageButton(LinearLayout row, String code, String flag) {
        Button button = button(flag, code.equals(language));
        button.setTextSize(24);
        button.setContentDescription(code);
        button.setOnClickListener(v -> {
            language = code;
            prefs.edit().putString("language", code).apply();
            buildLayout();
            navigate(Screen.admin(), false);
        });
        row.addView(button, new LinearLayout.LayoutParams(0, -2, 1));
    }

    private void addSyncAlertSettings() {
        LinearLayout panel = card();
        panel.addView(line(tr("sync_alert_help")));
        syncAlertEnabledInput = new CheckBox(this);
        syncAlertEnabledInput.setText(tr("sync_alert_enabled"));
        syncAlertEnabledInput.setTextColor(colorText);
        syncAlertEnabledInput.setChecked(prefs.getBoolean("sync_alert_enabled", true));
        panel.addView(syncAlertEnabledInput);
        syncAlertHoursInput = numberInput(String.valueOf(syncAlertHours()), tr("hours"));
        panel.addView(syncAlertHoursInput);
        episodeAlertEnabledInput = new CheckBox(this);
        episodeAlertEnabledInput.setText(tr("episode_alert_enabled"));
        episodeAlertEnabledInput.setTextColor(colorText);
        episodeAlertEnabledInput.setChecked(prefs.getBoolean("episode_alert_enabled", false));
        panel.addView(episodeAlertEnabledInput);
        hideEmptyCalendarDaysInput = new CheckBox(this);
        hideEmptyCalendarDaysInput.setText(tr("hide_empty_calendar_days"));
        hideEmptyCalendarDaysInput.setTextColor(colorText);
        hideEmptyCalendarDaysInput.setChecked(prefs.getBoolean("hide_empty_calendar_days", false));
        panel.addView(hideEmptyCalendarDaysInput);
        Button save = button(tr("save"), false);
        save.setOnClickListener(v -> saveSyncAlertSettings());
        panel.addView(save);
        content.addView(panel);
    }

    private void saveSyncAlertSettings() {
        int hours = clamp(parseInt(syncAlertHoursInput.getText().toString(), 24), 1, 720);
        boolean syncEnabled = syncAlertEnabledInput == null || syncAlertEnabledInput.isChecked();
        boolean episodeEnabled = episodeAlertEnabledInput != null && episodeAlertEnabledInput.isChecked();
        boolean hideEmptyDays = hideEmptyCalendarDaysInput != null && hideEmptyCalendarDaysInput.isChecked();
        prefs.edit()
                .putInt("sync_alert_hours", hours)
                .putBoolean("sync_alert_enabled", syncEnabled)
                .putBoolean("episode_alert_enabled", episodeEnabled)
                .putBoolean("hide_empty_calendar_days", hideEmptyDays)
                .apply();
        progress.setVisibility(ProgressBar.VISIBLE);
        executor.submit(() -> {
            try {
                JSONObject payload = new JSONObject()
                        .put("sync_alert_hours", hours)
                        .put("sync_alert_enabled", syncEnabled)
                        .put("episode_alert_enabled", episodeEnabled)
                        .put("hide_empty_calendar_days", hideEmptyDays);
                JSONObject response = postJsonSync("/api/mobile/settings", payload);
                JSONObject bootstrap = cachedJson("bootstrap");
                if (bootstrap != null) {
                    bootstrap.put("mobile_settings", response.optJSONObject("mobile_settings"));
                    writeCacheJson("bootstrap", bootstrap);
                }
                runOnUiThread(() -> {
                    progress.setVisibility(ProgressBar.GONE);
                    Toast.makeText(this, tr("sync_alert_saved"), Toast.LENGTH_SHORT).show();
                    render(Screen.admin());
                });
            } catch (Exception error) {
                runOnUiThread(() -> {
                    progress.setVisibility(ProgressBar.GONE);
                    Toast.makeText(this, tr("sync_failed") + ": " + error.getMessage(), Toast.LENGTH_LONG).show();
                    render(Screen.admin());
                });
            }
        });
    }

    private void addProfileSettings() {
        LinearLayout row = card();
        row.setOrientation(LinearLayout.VERTICAL);
        JSONObject bootstrap = cachedJson("bootstrap");
        JSONArray profiles = bootstrap == null ? null : bootstrap.optJSONArray("profiles");
        if (profiles == null || profiles.length() == 0) {
            row.addView(line(tr("profile_sync_required")));
            Button reload = button(tr("load_profiles"), true);
            reload.setOnClickListener(v -> refreshBootstrapOnly());
            row.addView(reload);
            content.addView(row);
            if (!bootstrapRefreshInFlight) {
                refreshBootstrapOnly();
            }
            return;
        }
        applyDefaultProfileFromBootstrap(bootstrap);
        Button reloadProfiles = button(tr("load_profiles"), false);
        reloadProfiles.setOnClickListener(v -> refreshBootstrapOnly());
        row.addView(reloadProfiles);
        for (int index = 0; index < profiles.length(); index++) {
            JSONObject profile = profiles.optJSONObject(index);
            if (profile == null) continue;
            String key = profile.optString("key", "");
            String label = profile.optString("label", key);
            Button button = button(label, key.equals(activeProfileKey));
            button.setContentDescription(tr("profile") + ": " + label);
            button.setOnClickListener(v -> {
                activeProfileKey = key;
                prefs.edit().putString("profile_key", key).apply();
                Toast.makeText(this, tr("profile_saved"), Toast.LENGTH_SHORT).show();
                synchronizeOfflineDatabase();
            });
            row.addView(button);
        }
        content.addView(row);
    }

    private void addMetaProfileSettings() {
        JSONObject bootstrap = cachedJson("bootstrap");
        JSONArray metaProfiles = bootstrap == null ? null : bootstrap.optJSONArray("meta_profiles");
        if (metaProfiles == null || metaProfiles.length() == 0) return;
        addSection(tr("meta_profiles"));
        LinearLayout panel = card();
        for (int index = 0; index < metaProfiles.length(); index++) {
            JSONObject profile = metaProfiles.optJSONObject(index);
            if (profile == null) continue;
            String label = profile.optString("label", profile.optString("key", ""));
            JSONObject platforms = profile.optJSONObject("platforms");
            String suffix = platforms == null ? "" : " · " + platforms.length() + " " + tr("platforms");
            panel.addView(line(label + suffix));
        }
        content.addView(panel);
    }

    private void addCreateMetaProfileSettings() {
        JSONObject bootstrap = cachedJson("bootstrap");
        JSONObject platformProfiles = bootstrap == null ? null : bootstrap.optJSONObject("platform_profiles");
        if (platformProfiles == null || platformProfiles.length() == 0) return;
        addSection(tr("create_profile"));
        LinearLayout panel = card();
        EditText labelInput = textInput("", tr("profile_label"));
        EditText keyInput = textInput("", tr("profile_key"));
        panel.addView(labelInput);
        panel.addView(keyInput);

        Map<String, Spinner> selectors = new LinkedHashMap<>();
        JSONArray platformNames = platformProfiles.names();
        if (platformNames != null) {
            List<String> sortedPlatforms = new ArrayList<>();
            for (int index = 0; index < platformNames.length(); index++) {
                sortedPlatforms.add(platformNames.optString(index));
            }
            sortedPlatforms.sort(String::compareTo);
            for (String platform : sortedPlatforms) {
                JSONArray profiles = platformProfiles.optJSONArray(platform);
                if (profiles == null || profiles.length() == 0) continue;
                panel.addView(titleText(platformLabel(platform), 15));
                List<String> values = new ArrayList<>();
                values.add(tr("ignore_platform"));
                for (int index = 0; index < profiles.length(); index++) {
                    JSONObject profile = profiles.optJSONObject(index);
                    if (profile == null) continue;
                    String name = profile.optString("platform_profile_name", "").trim();
                    if (!name.isEmpty() && !values.contains(name)) values.add(name);
                }
                if (values.size() <= 1) continue;
                Spinner spinner = new Spinner(this);
                spinner.setAdapter(new ArrayAdapter<>(this, android.R.layout.simple_spinner_dropdown_item, values));
                panel.addView(spinner);
                selectors.put(platform, spinner);
            }
        }

        Button create = button(tr("create_profile"), true);
        create.setOnClickListener(v -> createMetaProfile(labelInput, keyInput, selectors));
        panel.addView(create);
        content.addView(panel);
    }

    private void createMetaProfile(EditText labelInput, EditText keyInput, Map<String, Spinner> selectors) {
        String label = labelInput.getText().toString().trim();
        if (label.isEmpty()) {
            Toast.makeText(this, tr("profile_label_required"), Toast.LENGTH_SHORT).show();
            return;
        }
        progress.setVisibility(ProgressBar.VISIBLE);
        executor.submit(() -> {
            try {
                JSONObject platforms = new JSONObject();
                for (Map.Entry<String, Spinner> entry : selectors.entrySet()) {
                    Object selected = entry.getValue().getSelectedItem();
                    String profileName = selected == null ? "" : selected.toString().trim();
                    if (profileName.equals(tr("ignore_platform"))) profileName = "";
                    if (!profileName.isEmpty()) platforms.put(entry.getKey(), profileName);
                }
                JSONObject payload = new JSONObject()
                        .put("label", label)
                        .put("key", keyInput.getText().toString().trim())
                        .put("platforms", platforms);
                JSONObject response = postJsonSync("/api/mobile/profiles/meta", payload);
                JSONObject bootstrap = cachedJson("bootstrap");
                if (bootstrap != null) {
                    bootstrap.put("profiles", response.optJSONArray("profiles"));
                    bootstrap.put("meta_profiles", response.optJSONArray("meta_profiles"));
                    bootstrap.put("has_meta_profiles", true);
                    writeCacheJson("bootstrap", bootstrap);
                }
                runOnUiThread(() -> {
                    progress.setVisibility(ProgressBar.GONE);
                    Toast.makeText(this, tr("profile_saved"), Toast.LENGTH_SHORT).show();
                    render(Screen.admin());
                });
            } catch (Exception error) {
                runOnUiThread(() -> {
                    progress.setVisibility(ProgressBar.GONE);
                    Toast.makeText(this, tr("sync_failed") + ": " + error.getMessage(), Toast.LENGTH_LONG).show();
                });
            }
        });
    }

    private void addPlatformProfileSettings() {
        addSection(tr("streaming_profiles"));
        LinearLayout panel = card();
        JSONObject bootstrap = cachedJson("bootstrap");
        JSONObject platformProfiles = bootstrap == null ? null : bootstrap.optJSONObject("platform_profiles");
        if (platformProfiles == null || platformProfiles.length() == 0) {
            panel.addView(line(tr("platform_profiles_empty")));
            content.addView(panel);
            return;
        }
        JSONArray platforms = platformProfiles.names();
        if (platforms == null) {
            panel.addView(line(tr("platform_profiles_empty")));
            content.addView(panel);
            return;
        }
        List<String> platformNames = new ArrayList<>();
        for (int index = 0; index < platforms.length(); index++) {
            platformNames.add(platforms.optString(index));
        }
        platformNames.sort(String::compareTo);
        for (String platform : platformNames) {
            panel.addView(titleText(platformLabel(platform), 16));
            JSONArray profiles = platformProfiles.optJSONArray(platform);
            if (profiles == null || profiles.length() == 0) {
                panel.addView(line(tr("platform_profiles_empty")));
                continue;
            }
            for (int index = 0; index < profiles.length(); index++) {
                JSONObject profile = profiles.optJSONObject(index);
                if (profile == null) continue;
                String label = profile.optString("profile_label", profile.optString("profile_key"));
                String name = profile.optString("platform_profile_name", "");
                panel.addView(line(label + " -> " + (name.isEmpty() ? tr("not_configured") : name)));
            }
        }
        content.addView(panel);
    }

    private void addAdminKpis() {
        JSONObject series = cachedJson(cacheKeyForTitles("series"));
        JSONObject movies = cachedJson(cacheKeyForTitles("movie"));
        content.addView(kpiCard(tr("series"), series == null ? 0 : arrayLength(series.optJSONArray("items"))));
        content.addView(kpiCard(tr("movies"), movies == null ? 0 : arrayLength(movies.optJSONArray("items"))));
        addPlatformKpis(tr("series_by_platform"), series == null ? null : series.optJSONArray("items"));
        addPlatformKpis(tr("movies_by_platform"), movies == null ? null : movies.optJSONArray("items"));
    }

    private void addPlatformKpis(String title, JSONArray items) {
        LinearLayout card = card();
        card.addView(titleText(title, 16));
        if (items == null) {
            card.addView(line(tr("no_synced_data")));
            content.addView(card);
            return;
        }
        java.util.Map<String, Integer> counts = new java.util.TreeMap<>();
        for (int index = 0; index < items.length(); index++) {
            JSONObject item = items.optJSONObject(index);
            if (item == null) continue;
            String platform = item.optString("platform", "unknown");
            counts.put(platform, counts.getOrDefault(platform, 0) + 1);
        }
        for (java.util.Map.Entry<String, Integer> entry : counts.entrySet()) {
            card.addView(line(platformLabel(entry.getKey()) + " · " + entry.getValue()));
        }
        content.addView(card);
    }

    private void addIngestionStatuses() {
        addSection(tr("last_ingestions"));
        LinearLayout card = card();
        JSONObject bootstrap = cachedJson("bootstrap");
        JSONArray statuses = bootstrap == null ? null : bootstrap.optJSONArray("ingestion_statuses");
        if (statuses == null || statuses.length() == 0) {
            card.addView(line(tr("no_synced_data")));
            content.addView(card);
            return;
        }
        for (int index = 0; index < statuses.length(); index++) {
            JSONObject status = statuses.optJSONObject(index);
            if (status == null) continue;
            String state = status.optString("status");
            boolean ok = "ok".equalsIgnoreCase(state);
            boolean unknown = "unknown".equalsIgnoreCase(state);
            String updatedAt = status.optString("updated_at", "");
            String text = (ok ? "OK " : (unknown ? "? " : "KO "))
                    + status.optString("platform_label", status.optString("platform"))
                    + " - +" + status.optInt("inserted", 0)
                    + " - "
                    + (updatedAt.isEmpty() || "null".equals(updatedAt) ? tr("no_last_ingestion") : updatedAt);
            String error = status.optString("error", "");
            if (!ok && !error.isEmpty()) text += " - " + error;
            TextView row = line(text);
            row.setTextColor(ok ? Color.rgb(73, 190, 137) : (unknown ? colorMuted : Color.rgb(236, 95, 103)));
            card.addView(row);
        }
        content.addView(card);
    }

    private void addRpaControls() {
        LinearLayout panel = card();
        JSONObject bootstrap = cachedJson("bootstrap");
        JSONArray platforms = bootstrap == null ? null : bootstrap.optJSONArray("rpa_platforms");
        if (platforms == null || platforms.length() == 0) {
            panel.addView(line(tr("rpa_no_platforms")));
            Button reload = button(tr("load_profiles"), true);
            reload.setOnClickListener(v -> refreshBootstrapOnly());
            panel.addView(reload);
            content.addView(panel);
            return;
        }
        LinearLayout row = null;
        int column = 0;
        for (int index = 0; index < platforms.length(); index++) {
            JSONObject item = platforms.optJSONObject(index);
            if (item == null) continue;
            String platform = item.optString("platform", "");
            if (platform.isEmpty()) continue;
            if (row == null || column == 2) {
                row = new LinearLayout(this);
                row.setOrientation(LinearLayout.HORIZONTAL);
                panel.addView(row);
                column = 0;
            }
            Button run = button(platformLabel(platform), false);
            run.setTextColor(Color.rgb(8, 16, 24));
            run.setBackground(rounded(platformColor(platform), platformColor(platform), 8));
            run.setContentDescription(tr("rpa_restart") + ": " + platformLabel(platform));
            run.setOnClickListener(v -> triggerRpa(platform));
            LinearLayout.LayoutParams params = new LinearLayout.LayoutParams(0, -2, 1);
            params.setMargins(dp(3), dp(3), dp(3), dp(3));
            row.addView(run, params);
            column++;
        }
        content.addView(panel);
    }

    private LinearLayout kpiCard(String label, int count) {
        LinearLayout card = card();
        card.addView(titleText(label, 16));
        card.addView(titleText(String.valueOf(count), 28));
        return card;
    }

    private void addDebugLog() {
        addSection(tr("sync_debug"));
        LinearLayout card = card();
        card.addView(line(readDebugLog()));
        content.addView(card);
    }

    private void synchronizeOfflineDatabase() {
        prefs.edit().putString("server_url", normalizedServerUrl()).apply();
        progress.setVisibility(ProgressBar.VISIBLE);
        if (syncStatus != null) syncStatus.setText(tr("sync_running"));
        executor.submit(() -> {
            try {
                JSONObject bootstrap = fetchSync("/api/mobile/bootstrap");
                applyDefaultProfileFromBootstrap(bootstrap);
                applyMobileSettingsFromBootstrap(bootstrap);
                StringBuilder debug = new StringBuilder("Début synchro\n");
                JSONObject series = fetchAllTitles("series", fetchSync("/api/mobile/titles?type=series&per_page=100" + allProfilesQuery()));
                JSONObject movies = fetchAllTitles("movie", fetchSync("/api/mobile/titles?type=movie&per_page=100" + allProfilesQuery()));
                writeCacheJson(cacheKeyForTitles("series"), series);
                writeCacheJson(cacheKeyForTitles("movie"), movies);
                writeCacheJson("bootstrap", bootstrap);
                debug.append("Listes: séries=").append(arrayLength(series.optJSONArray("items")))
                        .append(", films=").append(arrayLength(movies.optJSONArray("items"))).append("\n");
                YearMonth firstMonth = YearMonth.now().minusMonths(6);
                JSONObject currentCalendar = null;
                for (int offset = 0; offset <= 18; offset++) {
                    YearMonth month = firstMonth.plusMonths(offset);
                    JSONObject calendar = fetchSync("/api/mobile/calendar?month=" + month + allProfilesQuery("&"));
                    writeCacheJson(cacheKeyForCalendar(month), calendar);
                    if (month.equals(YearMonth.now())) currentCalendar = calendar;
                }
                if (currentCalendar != null) writeCacheJson("calendar", currentCalendar);
                debug.append("Calendriers: 19 mois\n");
                List<Integer> ids = new ArrayList<>();
                collectIds(series.optJSONArray("items"), ids);
                collectIds(movies.optJSONArray("items"), ids);
                int count = 0;
                int detailErrors = 0;
                for (Integer itemId : ids) {
                    try {
                        JSONObject detail = fetchSync("/api/mobile/titles/" + itemId);
                        writeCacheJson(cacheKeyForDetail(itemId), detail);
                        cacheImage(detail.optString("poster_url"));
                        count++;
                    } catch (Exception detailError) {
                        detailErrors++;
                        debug.append("Détail KO id=").append(itemId).append(": ")
                                .append(detailError.getMessage()).append("\n");
                    }
                }
                cacheImages(series.optJSONArray("items"));
                cacheImages(movies.optJSONArray("items"));
                debug.append("Détails OK=").append(count).append(", erreurs=").append(detailErrors).append("\n");
                prefs.edit()
                        .putLong("last_sync_at", System.currentTimeMillis())
                        .putString("sync_debug", debug.toString())
                        .apply();
                int finalCount = count;
                runOnUiThread(() -> {
                    progress.setVisibility(ProgressBar.GONE);
                    Toast.makeText(this, tr("sync_done") + ": " + finalCount + " " + tr("cards"), Toast.LENGTH_LONG).show();
                    render(currentScreen);
                });
            } catch (Exception error) {
                runOnUiThread(() -> {
                    progress.setVisibility(ProgressBar.GONE);
                    Toast.makeText(this, tr("sync_failed") + ": " + error.getMessage(), Toast.LENGTH_LONG).show();
                    if (syncStatus != null) syncStatus.setText(lastSyncLabel());
                });
            }
        });
    }

    private void refreshBootstrapOnly() {
        prefs.edit().putString("server_url", normalizedServerUrl()).apply();
        if (bootstrapRefreshInFlight) return;
        bootstrapRefreshInFlight = true;
        progress.setVisibility(ProgressBar.VISIBLE);
        executor.submit(() -> {
            try {
                JSONObject bootstrap = fetchSync("/api/mobile/bootstrap");
                applyDefaultProfileFromBootstrap(bootstrap);
                applyMobileSettingsFromBootstrap(bootstrap);
                writeCacheJson("bootstrap", bootstrap);
                runOnUiThread(() -> {
                    bootstrapRefreshInFlight = false;
                    progress.setVisibility(ProgressBar.GONE);
                    render(Screen.admin());
                });
            } catch (Exception error) {
                runOnUiThread(() -> {
                    bootstrapRefreshInFlight = false;
                    progress.setVisibility(ProgressBar.GONE);
                    Toast.makeText(this, tr("sync_failed") + ": " + error.getMessage(), Toast.LENGTH_LONG).show();
                });
            }
        });
    }

    private void triggerRpa(String platform) {
        prefs.edit().putString("server_url", normalizedServerUrl()).apply();
        progress.setVisibility(ProgressBar.VISIBLE);
        executor.submit(() -> {
            try {
                JSONObject response = postSync("/api/mobile/rpa/" + url(platform) + "/run");
                JSONObject bootstrap = fetchSync("/api/mobile/bootstrap");
                writeCacheJson("bootstrap", bootstrap);
                String message = tr("rpa_queued") + ": "
                        + platformLabel(platform)
                        + " · "
                        + response.optString("log", "");
                runOnUiThread(() -> {
                    progress.setVisibility(ProgressBar.GONE);
                    Toast.makeText(this, message, Toast.LENGTH_LONG).show();
                    render(Screen.admin());
                });
            } catch (Exception error) {
                runOnUiThread(() -> {
                    progress.setVisibility(ProgressBar.GONE);
                    Toast.makeText(this, tr("rpa_failed") + ": " + error.getMessage(), Toast.LENGTH_LONG).show();
                });
            }
        });
    }

    private JSONObject fetchAllTitles(String type, JSONObject firstPage) throws Exception {
        JSONArray merged = new JSONArray();
        appendItems(merged, firstPage.optJSONArray("items"));
        int totalPages = Math.max(1, firstPage.optInt("total_pages", 1));
        for (int page = 2; page <= totalPages; page++) {
            appendItems(merged, fetchSync("/api/mobile/titles?type=" + url(type) + "&per_page=100&page=" + page + allProfilesQuery("&")).optJSONArray("items"));
        }
        firstPage.put("items", merged);
        return firstPage;
    }

    private void applyDefaultProfileFromBootstrap(JSONObject bootstrap) {
        if (bootstrap == null) return;
        JSONArray profiles = bootstrap.optJSONArray("profiles");
        if (activeProfileKey != null && !activeProfileKey.isEmpty()
                && profileExists(profiles, activeProfileKey)) {
            return;
        }
        String defaultKey = bootstrap.optString("default_profile_key", "");
        if (defaultKey.isEmpty() || !profileExists(profiles, defaultKey)) {
            defaultKey = firstProfileKey(profiles);
        }
        if (!defaultKey.isEmpty()) {
            activeProfileKey = defaultKey;
            prefs.edit().putString("profile_key", activeProfileKey).apply();
        }
    }

    private void applyMobileSettingsFromBootstrap(JSONObject bootstrap) {
        if (bootstrap == null) return;
        JSONObject settings = bootstrap.optJSONObject("mobile_settings");
        if (settings == null) return;
        prefs.edit()
                .putInt("sync_alert_hours", clamp(settings.optInt("sync_alert_hours", 24), 1, 720))
                .putBoolean("sync_alert_enabled", settings.optBoolean("sync_alert_enabled", true))
                .putBoolean("episode_alert_enabled", settings.optBoolean("episode_alert_enabled", false))
                .putBoolean("hide_empty_calendar_days", settings.optBoolean("hide_empty_calendar_days", false))
                .apply();
    }

    private boolean profileExists(JSONArray profiles, String key) {
        if (profiles == null || key == null || key.isEmpty()) return false;
        for (int index = 0; index < profiles.length(); index++) {
            JSONObject profile = profiles.optJSONObject(index);
            if (profile != null && key.equals(profile.optString("key", ""))) return true;
        }
        return false;
    }

    private String firstProfileKey(JSONArray profiles) {
        if (profiles == null || profiles.length() == 0) return "";
        JSONObject profile = profiles.optJSONObject(0);
        return profile == null ? "" : profile.optString("key", "");
    }

    private String profileQuery() {
        return profileQuery("&");
    }

    private String profileQuery(String separator) {
        if (activeProfileKey == null || activeProfileKey.isEmpty()) return "";
        return separator + "profile=" + url(activeProfileKey);
    }

    private String allProfilesQuery() {
        return allProfilesQuery("&");
    }

    private String allProfilesQuery(String separator) {
        return separator + "profile=all";
    }

    private boolean profileMatches(JSONObject item) {
        if (activeProfileKey == null || activeProfileKey.isEmpty()) return true;
        String itemProfile = item.optString("profile_key", "");
        return itemProfile.isEmpty() || activeProfileKey.equals(itemProfile);
    }

    private JSONObject fetchSync(String path) throws Exception {
        URL endpoint = new URL(normalizedServerUrl() + path);
        HttpURLConnection connection = (HttpURLConnection) endpoint.openConnection();
        connection.setConnectTimeout(5000);
        connection.setReadTimeout(20000);
        connection.setRequestProperty("Accept", "application/json");
        int status = connection.getResponseCode();
        InputStream responseStream = status >= 400 ? connection.getErrorStream() : connection.getInputStream();
        if (responseStream == null) throw new IllegalStateException("HTTP " + status);
        BufferedReader reader = new BufferedReader(new InputStreamReader(responseStream, StandardCharsets.UTF_8));
        StringBuilder body = new StringBuilder();
        String line;
        while ((line = reader.readLine()) != null) body.append(line);
        if (status >= 400) throw new IllegalStateException("HTTP " + status + ": " + body);
        return new JSONObject(body.toString());
    }

    private JSONObject postSync(String path) throws Exception {
        return postJsonSync(path, null);
    }

    private JSONObject postJsonSync(String path, JSONObject payload) throws Exception {
        URL endpoint = new URL(normalizedServerUrl() + path);
        HttpURLConnection connection = (HttpURLConnection) endpoint.openConnection();
        connection.setConnectTimeout(5000);
        connection.setReadTimeout(20000);
        connection.setRequestMethod("POST");
        connection.setRequestProperty("Accept", "application/json");
        if (payload != null) {
            connection.setRequestProperty("Content-Type", "application/json; charset=utf-8");
        }
        connection.setDoOutput(true);
        try (OutputStream output = connection.getOutputStream()) {
            byte[] body = payload == null ? new byte[0] : payload.toString().getBytes(StandardCharsets.UTF_8);
            output.write(body);
        }
        int status = connection.getResponseCode();
        InputStream responseStream = status >= 400 ? connection.getErrorStream() : connection.getInputStream();
        if (responseStream == null) throw new IllegalStateException("HTTP " + status);
        BufferedReader reader = new BufferedReader(new InputStreamReader(responseStream, StandardCharsets.UTF_8));
        StringBuilder body = new StringBuilder();
        String line;
        while ((line = reader.readLine()) != null) body.append(line);
        if (status >= 400) throw new IllegalStateException("HTTP " + status + ": " + body);
        return new JSONObject(body.toString());
    }

    private void loadImage(ImageView view, String value) {
        if (value == null || value.isEmpty() || "null".equals(value)) return;
        executor.submit(() -> {
            try {
                File cached = imageFile(value);
                Bitmap bitmap;
                if (cached.exists()) {
                    bitmap = BitmapFactory.decodeFile(cached.getAbsolutePath());
                } else {
                    HttpURLConnection connection = (HttpURLConnection) new URL(value).openConnection();
                    connection.setConnectTimeout(5000);
                    connection.setReadTimeout(10000);
                    bitmap = BitmapFactory.decodeStream(connection.getInputStream());
                }
                runOnUiThread(() -> view.setImageBitmap(bitmap));
            } catch (Exception ignored) {
            }
        });
    }

    private ImageView posterView(int width, int height) {
        ImageView view = new ImageView(this);
        view.setScaleType(ImageView.ScaleType.CENTER_CROP);
        view.setBackground(rounded(colorPanelAlt, colorLine, 8));
        view.setLayoutParams(new LinearLayout.LayoutParams(dp(width), dp(height)));
        return view;
    }

    private int tilePosterWidth() {
        DisplayMetrics metrics = getResources().getDisplayMetrics();
        int screenDp = Math.round(metrics.widthPixels / metrics.density);
        int columns = Math.max(1, gridColumns());
        int outerPadding = 32;
        int cellSpacing = columns * 6;
        int cardPadding = columns * 10;
        int available = Math.max(160, screenDp - outerPadding - cellSpacing - cardPadding);
        return clamp(available / columns, 72, 190);
    }

    private LinearLayout calendarPosterTile(JSONObject item) {
        LinearLayout tile = new LinearLayout(this);
        tile.setOrientation(LinearLayout.VERTICAL);
        tile.setPadding(0, 0, dp(10), 0);
        ImageView poster = posterView(88, 132);
        loadImage(poster, item.optString("poster_url"));
        tile.addView(poster);
        TextView title = titleText(item.optString("title"), 12);
        title.setMaxLines(2);
        tile.addView(title, new LinearLayout.LayoutParams(dp(88), -2));
        String episode = episodeCode(item);
        if (!episode.isEmpty()) tile.addView(line(episode));
        tile.setOnClickListener(v -> navigate(Screen.detail(item.optInt("serie_id")), true));
        return tile;
    }

    private void addPlatformBadges(LinearLayout parent, JSONObject payload) {
        LinearLayout row = new LinearLayout(this);
        row.setOrientation(LinearLayout.HORIZONTAL);
        JSONArray platforms = payload.optJSONArray("platforms");
        if (platforms != null && platforms.length() > 0) {
            for (int index = 0; index < platforms.length(); index++) {
                row.addView(platformBadge(platforms.optString(index)));
            }
        } else {
            row.addView(platformBadge(payload.optString("platform")));
        }
        parent.addView(row);
    }

    private TextView platformBadge(String platform) {
        TextView badge = line(platformLabel(platform));
        badge.setTextColor(Color.rgb(8, 16, 24));
        badge.setTypeface(null, Typeface.BOLD);
        badge.setGravity(Gravity.CENTER);
        badge.setPadding(dp(8), dp(4), dp(8), dp(4));
        badge.setBackground(rounded(platformColor(platform), platformColor(platform), 6));
        return badge;
    }

    private LinearLayout card() {
        LinearLayout card = new LinearLayout(this);
        card.setOrientation(LinearLayout.VERTICAL);
        card.setPadding(dp(14), dp(14), dp(14), dp(14));
        LinearLayout.LayoutParams params = new LinearLayout.LayoutParams(-1, -2);
        params.setMargins(0, dp(12), 0, 0);
        card.setLayoutParams(params);
        card.setBackground(rounded(colorPanel, colorLine, 8));
        return card;
    }

    private Button button(String label, boolean accent) {
        Button button = new Button(this);
        button.setText(label);
        styleButton(button, accent);
        return button;
    }

    private TextView titleText(String value, int sp) {
        TextView view = new TextView(this);
        view.setText(value == null ? "" : value);
        view.setTextSize(sp);
        view.setTextColor(colorText);
        view.setTypeface(null, Typeface.BOLD);
        view.setPadding(0, dp(4), 0, dp(4));
        return view;
    }

    private TextView line(String value) {
        TextView view = new TextView(this);
        view.setText(value == null || "null".equals(value) ? "" : value);
        view.setTextSize(14);
        view.setTextColor(colorMuted);
        view.setPadding(0, dp(4), 0, dp(4));
        return view;
    }

    private void addSection(String value) {
        TextView view = titleText(value, 20);
        view.setPadding(0, dp(18), 0, dp(6));
        content.addView(view);
    }

    private void addMessage(String value) {
        TextView view = line(value);
        view.setGravity(Gravity.CENTER);
        content.addView(view);
    }

    private void addNullable(LinearLayout parent, String value) {
        if (value != null && !value.isEmpty() && !"null".equals(value)) parent.addView(line(value));
    }

    private String episodeCode(JSONObject item) {
        String season = cleanOptional(item.optString("season", ""));
        String episode = cleanOptional(item.optString("episode", ""));
        if (season.isEmpty() && episode.isEmpty()) return "";
        if (season.isEmpty()) return "E" + episode;
        if (episode.isEmpty()) return "S" + season;
        return "S" + season + "E" + episode;
    }

    private static String cleanOptional(String value) {
        if (value == null) return "";
        String trimmed = value.trim();
        return trimmed.isEmpty() || "null".equalsIgnoreCase(trimmed) || "?".equals(trimmed)
                ? ""
                : trimmed;
    }

    private void openDeepLink(String value) {
        if (value == null || value.isEmpty() || "null".equals(value)) {
            Toast.makeText(this, tr("no_platform_link"), Toast.LENGTH_SHORT).show();
            return;
        }
        startActivity(new Intent(Intent.ACTION_VIEW, Uri.parse(value)));
    }

    private String tr(String key) {
        switch (language) {
            case "en":
                return translateEn(key);
            case "es":
                return translateEs(key);
            default:
                return translateFr(key);
        }
    }

    private static String translateFr(String key) {
        switch (key) {
            case "admin": return "Admin";
            case "alerts": return "Alertes";
            case "app_version": return "Version application";
            case "calendar": return "Calendrier";
            case "calendar_unavailable": return "Calendrier offline indisponible. Va dans Admin puis lance Synchro.";
            case "cards": return "fiches";
            case "columns_hint": return "Colonnes 1-4";
            case "create_profile": return "Créer un profil";
            case "detail_unavailable": return "Détail indisponible offline. Relance une Synchro.";
            case "display": return "Affichage";
            case "display_help": return "Grille: colonnes 1 à 4. Pagination: nombre de lignes max par page.";
            case "display_saved": return "Affichage enregistré";
            case "episodes_seen": return "épisodes vus";
            case "episode_alert_enabled": return "Alerte nouvel épisode disponible";
            case "general": return "Général";
            case "hide_empty_calendar_days": return "Masquer les jours sans sortie";
            case "ignore_platform": return "Ignorer cette plateforme";
            case "language": return "Langue";
            case "last_ingestions": return "Dernières ingestions";
            case "last_sync": return "Dernière synchro";
            case "last_seen": return "Derniers vus";
            case "hours": return "Heures";
            case "load_profiles": return "Charger les profils";
            case "meta_profiles": return "Méta-profils";
            case "movies": return "Films";
            case "movies_by_platform": return "Films par plateforme";
            case "next": return "Suivant";
            case "no_data": return "Aucune donnée.";
            case "no_last_ingestion": return "Jamais ingéré";
            case "not_configured": return "Non configuré";
            case "no_sync_yet": return "Aucune synchro lancée depuis cette installation.";
            case "no_offline_data": return "Aucune donnée offline. Va dans Admin puis lance Synchro.";
            case "no_platform_link": return "Aucun lien plateforme disponible";
            case "no_previous_screen": return "Aucun écran précédent n'est disponible.";
            case "no_synced_data": return "Aucune donnée synchronisée.";
            case "offline_kpis": return "KPIs offline";
            case "offline_not_synced": return "Offline non synchronisé";
            case "open_platform": return "Ouvrir sur la plateforme";
            case "page": return "Page";
            case "previous": return "Précédent";
            case "profile": return "Profil";
            case "profile_key": return "Clé technique";
            case "profile_label": return "Nom du profil";
            case "profile_label_required": return "Le nom du profil est obligatoire";
            case "profile_progress": return "Progression par profil";
            case "platforms": return "plateformes";
            case "profile_saved": return "Profil enregistré";
            case "profile_sync_required": return "Lance une synchro pour charger les profils disponibles.";
            case "quit": return "Quitter";
            case "recent_history": return "Historique récent";
            case "resume": return "Reprendre";
            case "resume_empty": return "Aucun titre en cours dans le cache offline.";
            case "rows_hint": return "Lignes max par page";
            case "rpa_failed": return "Relance RPA impossible";
            case "rpa_no_platforms": return "Aucune plateforme RPA configurée.";
            case "rpa_queued": return "RPA ajouté à la file";
            case "rpa_restart": return "Relance RPA";
            case "save": return "Enregistrer";
            case "save_display": return "Enregistrer l'affichage";
            case "search_offline": return "Rechercher dans le cache offline";
            case "series": return "Séries";
            case "series_by_platform": return "Séries par plateforme";
            case "server_connection": return "Connexion au serveur";
            case "stay": return "Rester";
            case "streaming_profiles": return "Profils streaming";
            case "platform_profiles_empty": return "Aucun profil de plateforme configuré.";
            case "sync_debug": return "Debug synchro";
            case "sync_done": return "Synchro terminée";
            case "sync_failed": return "Synchro impossible";
            case "sync_alert": return "Alerte synchro";
            case "sync_alert_enabled": return "Activer l'alerte de synchro";
            case "sync_alert_help": return "Prévenir si la dernière synchro dépasse ce nombre d'heures.";
            case "sync_alert_saved": return "Alerte synchro enregistrée";
            case "sync_too_old": return "Alerte: synchro trop ancienne";
            case "sync_now": return "Synchroniser maintenant";
            case "sync_running": return "Synchronisation en cours...";
            case "title_az": return "Titre A-Z";
            case "titles": return "titres";
            case "upcoming": return "Prochaines sorties";
            default: return key;
        }
    }

    private static String translateEn(String key) {
        switch (key) {
            case "admin": return "Admin";
            case "alerts": return "Alerts";
            case "app_version": return "App version";
            case "calendar": return "Calendar";
            case "calendar_unavailable": return "Offline calendar unavailable. Go to Admin and run Sync.";
            case "cards": return "cards";
            case "columns_hint": return "Columns 1-4";
            case "create_profile": return "Create profile";
            case "detail_unavailable": return "Detail unavailable offline. Run Sync again.";
            case "display": return "Display";
            case "display_help": return "Grid: 1 to 4 columns. Pagination: maximum rows per page.";
            case "display_saved": return "Display saved";
            case "episodes_seen": return "episodes watched";
            case "episode_alert_enabled": return "New episode availability alert";
            case "general": return "General";
            case "hide_empty_calendar_days": return "Hide days without releases";
            case "ignore_platform": return "Ignore this platform";
            case "language": return "Language";
            case "last_ingestions": return "Latest ingestions";
            case "last_sync": return "Last sync";
            case "last_seen": return "Last watched";
            case "hours": return "Hours";
            case "load_profiles": return "Load profiles";
            case "meta_profiles": return "Meta profiles";
            case "movies": return "Movies";
            case "movies_by_platform": return "Movies by platform";
            case "next": return "Next";
            case "no_data": return "No data.";
            case "no_last_ingestion": return "Never ingested";
            case "not_configured": return "Not configured";
            case "no_sync_yet": return "No sync has run on this installation.";
            case "no_offline_data": return "No offline data. Go to Admin and run Sync.";
            case "no_platform_link": return "No platform link available";
            case "no_previous_screen": return "No previous screen is available.";
            case "no_synced_data": return "No synced data.";
            case "offline_kpis": return "Offline KPIs";
            case "offline_not_synced": return "Offline not synced";
            case "open_platform": return "Open on platform";
            case "page": return "Page";
            case "previous": return "Previous";
            case "profile": return "Profile";
            case "profile_key": return "Technical key";
            case "profile_label": return "Profile name";
            case "profile_label_required": return "Profile name is required";
            case "profile_progress": return "Profile progress";
            case "platforms": return "platforms";
            case "profile_saved": return "Profile saved";
            case "profile_sync_required": return "Run a sync to load available profiles.";
            case "quit": return "Quit";
            case "recent_history": return "Recent history";
            case "resume": return "Resume";
            case "resume_empty": return "No in-progress title in offline cache.";
            case "rows_hint": return "Max rows per page";
            case "rpa_failed": return "Unable to queue RPA";
            case "rpa_no_platforms": return "No RPA platform configured.";
            case "rpa_queued": return "RPA queued";
            case "rpa_restart": return "Restart RPA";
            case "save": return "Save";
            case "save_display": return "Save display";
            case "search_offline": return "Search offline cache";
            case "series": return "Series";
            case "series_by_platform": return "Series by platform";
            case "server_connection": return "Server connection";
            case "stay": return "Stay";
            case "streaming_profiles": return "Streaming profiles";
            case "platform_profiles_empty": return "No platform profile configured.";
            case "sync_debug": return "Sync debug";
            case "sync_done": return "Sync complete";
            case "sync_failed": return "Sync failed";
            case "sync_alert": return "Sync alert";
            case "sync_alert_enabled": return "Enable sync alert";
            case "sync_alert_help": return "Warn when the latest sync is older than this many hours.";
            case "sync_alert_saved": return "Sync alert saved";
            case "sync_too_old": return "Alert: sync is too old";
            case "sync_now": return "Sync now";
            case "sync_running": return "Sync in progress...";
            case "title_az": return "Title A-Z";
            case "titles": return "titles";
            case "upcoming": return "Upcoming";
            default: return key;
        }
    }

    private static String translateEs(String key) {
        switch (key) {
            case "admin": return "Admin";
            case "alerts": return "Alertas";
            case "app_version": return "Versión de la aplicación";
            case "calendar": return "Calendario";
            case "calendar_unavailable": return "Calendario offline no disponible. Ve a Admin y lanza Synchro.";
            case "cards": return "fichas";
            case "columns_hint": return "Columnas 1-4";
            case "create_profile": return "Crear perfil";
            case "detail_unavailable": return "Detalle no disponible offline. Lanza Synchro de nuevo.";
            case "display": return "Visualización";
            case "display_help": return "Cuadrícula: 1 a 4 columnas. Paginación: filas máximas por página.";
            case "display_saved": return "Visualización guardada";
            case "episodes_seen": return "episodios vistos";
            case "episode_alert_enabled": return "Alerta de nuevo episodio disponible";
            case "general": return "General";
            case "hide_empty_calendar_days": return "Ocultar días sin estrenos";
            case "ignore_platform": return "Ignorar esta plataforma";
            case "language": return "Idioma";
            case "last_ingestions": return "Últimas ingestas";
            case "last_sync": return "Última synchro";
            case "last_seen": return "Últimos vistos";
            case "hours": return "Horas";
            case "load_profiles": return "Cargar perfiles";
            case "meta_profiles": return "Metaperfiles";
            case "movies": return "Películas";
            case "movies_by_platform": return "Películas por plataforma";
            case "next": return "Siguiente";
            case "no_data": return "Sin datos.";
            case "no_last_ingestion": return "Nunca ingerido";
            case "not_configured": return "No configurado";
            case "no_sync_yet": return "No se ha lanzado ninguna synchro en esta instalación.";
            case "no_offline_data": return "Sin datos offline. Ve a Admin y lanza Synchro.";
            case "no_platform_link": return "Sin enlace de plataforma disponible";
            case "no_previous_screen": return "No hay pantalla anterior disponible.";
            case "no_synced_data": return "Sin datos sincronizados.";
            case "offline_kpis": return "KPIs offline";
            case "offline_not_synced": return "Offline no sincronizado";
            case "open_platform": return "Abrir en la plataforma";
            case "page": return "Página";
            case "previous": return "Anterior";
            case "profile": return "Perfil";
            case "profile_key": return "Clave técnica";
            case "profile_label": return "Nombre del perfil";
            case "profile_label_required": return "El nombre del perfil es obligatorio";
            case "profile_progress": return "Progresión por perfil";
            case "platforms": return "plataformas";
            case "profile_saved": return "Perfil guardado";
            case "profile_sync_required": return "Lanza una sincronización para cargar los perfiles disponibles.";
            case "quit": return "Salir";
            case "recent_history": return "Historial reciente";
            case "resume": return "Reanudar";
            case "resume_empty": return "No hay títulos en curso en la caché offline.";
            case "rows_hint": return "Filas max por página";
            case "rpa_failed": return "No se puede relanzar RPA";
            case "rpa_no_platforms": return "Ninguna plataforma RPA configurada.";
            case "rpa_queued": return "RPA añadido a la cola";
            case "rpa_restart": return "Relanzar RPA";
            case "save": return "Guardar";
            case "save_display": return "Guardar visualización";
            case "search_offline": return "Buscar en caché offline";
            case "series": return "Series";
            case "series_by_platform": return "Series por plataforma";
            case "server_connection": return "Conexión al servidor";
            case "stay": return "Quedarse";
            case "streaming_profiles": return "Perfiles streaming";
            case "platform_profiles_empty": return "Ningún perfil de plataforma configurado.";
            case "sync_debug": return "Debug de sincronización";
            case "sync_done": return "Synchro terminada";
            case "sync_failed": return "Synchro imposible";
            case "sync_alert": return "Alerta de sincronización";
            case "sync_alert_enabled": return "Activar alerta de sincronización";
            case "sync_alert_help": return "Avisar si la última sincronización supera este número de horas.";
            case "sync_alert_saved": return "Alerta de sincronización guardada";
            case "sync_too_old": return "Alerta: sincronización demasiado antigua";
            case "sync_now": return "Sincronizar ahora";
            case "sync_running": return "Sincronización en curso...";
            case "title_az": return "Título A-Z";
            case "titles": return "títulos";
            case "upcoming": return "Próximas salidas";
            default: return key;
        }
    }

    private JSONObject cachedJson(String key) {
        try {
            File file = cacheFile(key);
            String value = file.exists()
                    ? new String(Files.readAllBytes(file.toPath()), StandardCharsets.UTF_8)
                    : prefs.getString("cache_" + key, "");
            return value.isEmpty() ? null : new JSONObject(value);
        } catch (Exception error) {
            return null;
        }
    }

    private void writeCacheJson(String key, JSONObject payload) throws Exception {
        File file = cacheFile(key);
        File parent = file.getParentFile();
        if (parent != null) parent.mkdirs();
        try (FileOutputStream output = new FileOutputStream(file)) {
            output.write(payload.toString().getBytes(StandardCharsets.UTF_8));
        }
    }

    private File cacheFile(String key) {
        return new File(new File(getFilesDir(), "mobile-cache"), safeFileName(key) + ".json");
    }

    private String readDebugLog() {
        String value = prefs.getString("sync_debug", "");
        return value.isEmpty() ? tr("no_sync_yet") : value;
    }

    private String normalizedServerUrl() {
        String value = serverInput == null ? prefs.getString("server_url", "") : serverInput.getText().toString().trim();
        return value.endsWith("/") ? value.substring(0, value.length() - 1) : value;
    }

    private String currentQuery() {
        return searchInput == null ? "" : searchInput.getText().toString().trim().toLowerCase();
    }

    private static boolean titleMatches(JSONObject item, String query) {
        if (query == null || query.isEmpty()) return true;
        return item.optString("title", "").toLowerCase().contains(query)
                || item.optString("episode_title", "").toLowerCase().contains(query);
    }

    private void cacheImages(JSONArray items) {
        if (items == null) return;
        for (int index = 0; index < items.length(); index++) {
            JSONObject item = items.optJSONObject(index);
            if (item != null) cacheImage(item.optString("poster_url"));
        }
    }

    private void cacheImage(String value) {
        if (value == null || value.isEmpty() || "null".equals(value)) return;
        try {
            File file = imageFile(value);
            if (file.exists()) return;
            File parent = file.getParentFile();
            if (parent != null) parent.mkdirs();
            HttpURLConnection connection = (HttpURLConnection) new URL(value).openConnection();
            connection.setConnectTimeout(5000);
            connection.setReadTimeout(10000);
            try (InputStream input = connection.getInputStream(); FileOutputStream output = new FileOutputStream(file)) {
                byte[] buffer = new byte[8192];
                int read;
                while ((read = input.read(buffer)) != -1) output.write(buffer, 0, read);
            }
        } catch (Exception ignored) {
        }
    }

    private File imageFile(String value) throws Exception {
        return new File(new File(getFilesDir(), "image-cache"), sha256(value) + ".img");
    }

    private int gridColumns() {
        return clamp(prefs.getInt("grid_columns", 4), 1, 4);
    }

    private int maxRowsPerPage() {
        return clamp(prefs.getInt("max_rows_per_page", 4), 1, 20);
    }

    private int pageSize() {
        return clamp(gridColumns() * maxRowsPerPage(), 1, 80);
    }

    private EditText numberInput(String value, String hint) {
        EditText input = new EditText(this);
        input.setText(value);
        input.setHint(hint);
        input.setInputType(android.text.InputType.TYPE_CLASS_NUMBER);
        input.setKeyListener(DigitsKeyListener.getInstance("0123456789"));
        styleInput(input);
        return input;
    }

    private EditText textInput(String value, String hint) {
        EditText input = new EditText(this);
        input.setText(value);
        input.setHint(hint);
        styleInput(input);
        return input;
    }

    private static int parseInt(String value, int fallback) {
        try {
            return Integer.parseInt(value);
        } catch (Exception error) {
            return fallback;
        }
    }

    private static int clamp(int value, int min, int max) {
        return Math.max(min, Math.min(max, value));
    }

    private static int arrayLength(JSONArray items) {
        return items == null ? 0 : items.length();
    }

    private static String safeFileName(String value) {
        return value.replaceAll("[^a-zA-Z0-9_.-]", "_");
    }

    private static String sha256(String value) throws Exception {
        MessageDigest digest = MessageDigest.getInstance("SHA-256");
        byte[] bytes = digest.digest(value.getBytes(StandardCharsets.UTF_8));
        StringBuilder builder = new StringBuilder();
        for (byte b : bytes) builder.append(String.format("%02x", b));
        return builder.toString();
    }

    private static String platformLabel(String platform) {
        if ("crunchyroll".equals(platform)) return "Crunchyroll";
        if ("netflix".equals(platform)) return "Netflix";
        if ("prime_video".equals(platform)) return "Prime Video";
        if ("disney_plus".equals(platform)) return "Disney+";
        if ("canal_plus".equals(platform)) return "CANAL+";
        return platform == null || platform.isEmpty() ? "Inconnu" : platform;
    }

    private static int platformColor(String platform) {
        if ("crunchyroll".equals(platform)) return Color.rgb(244, 117, 33);
        if ("netflix".equals(platform)) return Color.rgb(229, 9, 20);
        if ("prime_video".equals(platform)) return Color.rgb(25, 167, 224);
        if ("disney_plus".equals(platform)) return Color.rgb(21, 60, 116);
        if ("canal_plus".equals(platform)) return Color.rgb(243, 244, 246);
        return Color.rgb(79, 179, 255);
    }

    private static void collectIds(JSONArray items, List<Integer> ids) {
        if (items == null) return;
        Set<Integer> seen = new HashSet<>(ids);
        for (int index = 0; index < items.length(); index++) {
            JSONObject item = items.optJSONObject(index);
            int id = item == null ? 0 : item.optInt("id", 0);
            if (id > 0 && seen.add(id)) ids.add(id);
        }
    }

    private static void appendItems(JSONArray target, JSONArray source) {
        if (source == null) return;
        for (int index = 0; index < source.length(); index++) target.put(source.opt(index));
    }

    private int syncAlertHours() {
        int stored = prefs.getInt("sync_alert_hours", -1);
        if (stored > 0) return clamp(stored, 1, 720);
        JSONObject bootstrap = cachedJson("bootstrap");
        JSONObject settings = bootstrap == null ? null : bootstrap.optJSONObject("mobile_settings");
        return clamp(settings == null ? 24 : settings.optInt("sync_alert_hours", 24), 1, 720);
    }

    private String lastSyncLabel() {
        long value = prefs.getLong("last_sync_at", 0L);
        if (value <= 0L) return tr("offline_not_synced");
        java.text.DateFormat date = android.text.format.DateFormat.getDateFormat(this);
        java.text.DateFormat time = android.text.format.DateFormat.getTimeFormat(this);
        String label = tr("last_sync") + ": " + date.format(value) + " " + time.format(value);
        long maxAgeMs = syncAlertHours() * 60L * 60L * 1000L;
        if (prefs.getBoolean("sync_alert_enabled", true)
                && System.currentTimeMillis() - value > maxAgeMs) {
            label += " · " + tr("sync_too_old") + " > " + syncAlertHours() + "h";
        }
        return label;
    }

    private void styleInput(EditText input) {
        input.setTextColor(colorText);
        input.setHintTextColor(colorMuted);
        input.setPadding(dp(14), dp(8), dp(14), dp(8));
        input.setSingleLine(true);
        input.setBackground(rounded(colorPanel, colorLine, 8));
    }

    private void styleButton(Button button, boolean accent) {
        button.setTextColor(accent ? Color.rgb(8, 16, 24) : colorText);
        button.setTypeface(null, Typeface.BOLD);
        button.setAllCaps(false);
        button.setBackground(rounded(accent ? colorAccent : colorPanelAlt, accent ? colorAccent : colorLine, 8));
    }

    private GradientDrawable rounded(int fill, int stroke, int radiusDp) {
        GradientDrawable drawable = new GradientDrawable();
        drawable.setColor(fill);
        drawable.setStroke(1, stroke);
        drawable.setCornerRadius(dp(radiusDp));
        return drawable;
    }

    private LinearLayout.LayoutParams matchWrap() {
        LinearLayout.LayoutParams params = new LinearLayout.LayoutParams(-1, -2);
        params.setMargins(0, dp(8), 0, dp(8));
        return params;
    }

    private int dp(int value) {
        return Math.round(value * getResources().getDisplayMetrics().density);
    }

    private static String url(String value) {
        try {
            return URLEncoder.encode(value, StandardCharsets.UTF_8.name());
        } catch (UnsupportedEncodingException error) {
            return value;
        }
    }

    private String cacheKeyForTitles(String type) {
        return "titles_all_" + type;
    }

    private static String cacheKeyForDetail(int id) {
        return "detail_" + id;
    }

    private String cacheKeyForCalendar(YearMonth month) {
        return "calendar_all_" + month;
    }

    private String safeCacheProfile() {
        String value = activeProfileKey == null || activeProfileKey.isEmpty()
                ? "default"
                : activeProfileKey;
        return value.replaceAll("[^A-Za-z0-9_-]", "_");
    }

    private static final class Screen {
        final String kind;
        final String type;
        final int page;
        final int id;
        final YearMonth month;

        private Screen(String kind, String type, int page, int id, YearMonth month) {
            this.kind = kind;
            this.type = type;
            this.page = page;
            this.id = id;
            this.month = month;
        }

        static Screen titles(String type, int page) {
            return new Screen("titles", type, page, 0, YearMonth.now());
        }

        static Screen detail(int id) {
            return new Screen("detail", "", 0, id, YearMonth.now());
        }

        static Screen calendar(YearMonth month) {
            return new Screen("calendar", "", 0, 0, month);
        }

        static Screen resume(int page) {
            return new Screen("resume", "", page, 0, YearMonth.now());
        }

        static Screen admin() {
            return new Screen("admin", "", 0, 0, YearMonth.now());
        }

        Screen withPage(int nextPage) {
            if ("titles".equals(kind)) return titles(type, nextPage);
            if ("resume".equals(kind)) return resume(nextPage);
            return this;
        }
    }
}
