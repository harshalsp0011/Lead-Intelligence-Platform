# Grafana Dashboard Configuration

## Overview

Grafana dashboard for visualizing Utility Lead Platform metrics in real-time.

**Dashboard File**: `dashboard.json`

**Update Frequency**: Every 30 seconds

**Default Time Range**: Last 7 days

**Tags**: leads, pipeline, troy-banks

## Panels Overview

### Panel 1: Pipeline Overview (Top - Full Width)
**Type**: Stat panels  
**Metrics**:
- High Tier leads (green)
- Medium Tier leads (yellow)
- Low Tier leads (gray)

**Data Source**: Prometheus `leads_by_tier_total` counter  
**Refresh**: Every 30 seconds

**Use Case**: Quick snapshot of current lead quality distribution across tiers.

---

### Panel 2: Leads Found Over Time (8 rows, left column)
**Type**: Time series line chart  
**Metric**: `leads_found_total` (cumulative counter)  
**X-Axis**: Time  
**Y-Axis**: Cumulative leads found  
**Time Range**: Last 30 days  
**Refresh**: Every 5 minutes

**Legend**: Shows mean and max values  
**Use Case**: Track Scout agent's discovery velocity over the month.

---

### Panel 3: Email Performance (8 rows, right column)
**Type**: Bar chart  
**Metrics**:
- Emails Sent (blue bars)
- Emails Opened (yellow bars)
- Emails Replied (green bars)

**Data Source**: Prometheus email metrics  
**Refresh**: Every 5 minutes  
**Legend**: Displayed below chart

**Use Case**: Compare email campaign volumes across stages.

---

### Panel 4a: Open Rate Stat (4 rows, left under email)
**Type**: Stat panel  
**Formula**: `(emails_opened_total / emails_sent_total) * 100`  
**Unit**: Percentage  
**Thresholds**:
- Red: < 20%
- Yellow: 20-40%
- Green: ≥ 40%

**Use Case**: Monitor email engagement quality.

---

### Panel 4b: Reply Rate Stat (4 rows, middle under email)
**Type**: Stat panel  
**Formula**: `(emails_replied_total / emails_sent_total) * 100`  
**Unit**: Percentage  
**Thresholds**:
- Red: < 5%
- Yellow: 5-10%
- Green: ≥ 10%

**Use Case**: Track conversion to meaningful responses.

---

### Panel 5: Pipeline Value Over Time (8 rows, right of stats)
**Type**: Time series area chart  
**Metric**: `pipeline_value_dollars` (gauge)  
**Color**: Green fill (100% opacity)  
**Time Range**: Last 30 days  
**Unit**: USD  
**Refresh**: Every 5 minutes

**Legend**: Shows mean, max, and min values  
**Use Case**: Visualize pipeline health and growth over time.

---

### Panel 6: Agent Run Durations (8 rows, left)
**Type**: Heatmap  
**Metric**: `agent_run_duration_seconds` (histogram)  
**Legend Format**: Bucket boundaries (le)  
**Refresh**: Every 5 minutes

**Use Case**: Identify bottlenecks and slow agents in the pipeline. Darker areas = longer runs.

---

### Panel 7: Error Rate by Agent (8 rows, right)
**Type**: Time series line chart  
**Metric**: `increase(agent_errors_total[1h]) by (agent_name)`  
**Refresh**: Every 1 minute  
**Legend**: Shows max and mean errors per agent

**Alert Threshold**: Lines turn red when > 5 errors/hour  
**Color Coding**:
- Green: 0-3 errors/hour (healthy)
- Yellow: 3-5 errors/hour (warning)
- Red: > 5 errors/hour (alert)

**Line Color**: Red (warnings)  
**Use Case**: Rapid error detection for each agent (scout, analyst, writer, tracker, outreach, orchestrator).

---

### Panel 8: Daily Activity Summary (8 rows, full width)
**Type**: Table  
**Columns**:
- Time
- Companies Found (leads_found_total)
- Companies Scored (leads_scored_total)
- Emails Sent (emails_sent_total)
- Emails Replied (emails_replied_total)

**Refresh**: Every 5 minutes  
**Sortable**: Yes (default by Time descending)  
**Filterable**: Yes

**Use Case**: Detailed daily metrics for reporting and analysis.

---

## Setup Instructions

### Import Dashboard into Grafana

1. **Via UI (Recommended)**:
   - Open Grafana at http://localhost:3000
   - Navigate to **Dashboards → + New → Import**
   - Click **Upload JSON file**
   - Select `monitoring/grafana/dashboard.json`
   - Select **Prometheus** as data source
   - Click **Import**

2. **Via Docker Volume**:
   ```yaml
   # In docker-compose.yml under grafana service:
   volumes:
     - ./monitoring/grafana/dashboard.json:/var/lib/grafana/dashboards/dashboard.json
     - ./monitoring/grafana/provisioning:/etc/grafana/provisioning
   ```

3. **Via Grafana Provisioning** (Advanced):
   Create `monitoring/grafana/provisioning/dashboards/dashboard.yml`:
   ```yaml
   apiVersion: 1
   providers:
     - name: 'Utility Lead Platform'
       orgId: 1
       folder: ''
       type: file
       disableDeletion: false
       updateIntervalSeconds: 10
       allowUiUpdates: true
       options:
         path: /var/lib/grafana/dashboards
   ```

### Prerequisites

- Grafana 8.0+ running on http://localhost:3000
- Prometheus data source configured
  - URL: http://localhost:9090
  - Name: "Prometheus" (must match dashboard config)
- Prometheus metrics available (confirm in Prometheus UI first)

### Verify Dashboard

After import:
1. Dashboard should display at http://localhost:3000/d/utility-lead-platform
2. All panels should load with blue "Loading..." state initially
3. After 30 seconds, panels should show data (or "No data" if metrics absent)
4. Check Prometheus → Status → Targets to ensure all jobs are green

## Customization

### Add New Panels

Edit `dashboard.json` and add objects to the `panels` array. Example:

```json
{
  "id": 10,
  "gridPos": { "h": 8, "w": 12, "x": 0, "y": 40 },
  "type": "timeseries",
  "title": "My Custom Panel",
  "datasource": "Prometheus",
  "targets": [
    {
      "expr": "my_custom_metric",
      "refId": "A"
    }
  ]
}
```

### Adjust Thresholds

In any stat panel, modify `fieldConfig.defaults.thresholds.steps`:

```json
"thresholds": {
  "mode": "percentage",
  "steps": [
    { "color": "red", "value": null },
    { "color": "yellow", "value": 20 },
    { "color": "green", "value": 40 }
  ]
}
```

### Change Refresh Rate

Global dashboard refresh:
- Edit JSON: Change `"refresh": "30s"` to desired interval
- Via UI: Click dashboard settings → "Refresh" dropdown

Per-panel refresh:
- Add `"interval": "5m"` to any panel's JSON

### Add Alerts

In Grafana UI:
1. Click on any panel
2. **Edit** → **Alert** tab
3. Configure alert rules and notification channels

## Troubleshooting

### No Data in Panels

**Cause**: Metrics not being scraped  
**Solution**:
1. Verify Prometheus is collecting metrics:
   - Open http://localhost:9090
   - Go to Status → Targets
   - Ensure all 3 jobs show green "UP"
2. Check if metrics exist:
   - In Prometheus, type metric name in query box (e.g., `leads_found_total`)
   - If no data appears, metric hasn't been created in API yet
3. Verify data source:
   - Dashboard settings → Data Sources
   - "Prometheus" should be listed

### All Panels Show "No Data"

**Cause**: Prometheus data source misconfigured  
**Solution**:
```bash
# Test Prometheus connectivity
curl http://localhost:9090/api/v1/query?query=up
# Should return: {"status":"success","data":{"result":[...]}}
```

### Dashboard Shows Old Timestamp

**Cause**: Time range set incorrectly  
**Solution**:
- Top-right of dashboard: Verify time range is "Last 7 days"
- Click refresh button (circular arrow icon)

### Panel Shows Error

**Common Errors**:
- `unsupported_parser_type`: Metric format issue (verify JSON)
- `status code 400`: Invalid PromQL query (check Prometheus syntax)
- `status code 401`: Prometheus auth required (update data source)

## Production Deployment

### Docker Compose Setup

Add to `docker-compose.yml`:

```yaml
grafana:
  image: grafana/grafana:latest
  container_name: grafana
  ports:
    - "3000:3000"
  environment:
    - GF_SECURITY_ADMIN_PASSWORD=admin
    - GF_INSTALL_PLUGINS=grafana-piechart-panel
  volumes:
    - ./monitoring/grafana/dashboard.json:/var/lib/grafana/dashboards/dashboard.json
    - grafana_data:/var/lib/grafana
  depends_on:
    - prometheus
  networks:
    - utility-lead-network

volumes:
  grafana_data:

networks:
  utility-lead-network:
    driver: bridge
```

### Enable Persistent Storage

```bash
# Create volume for Grafana data
docker volume create grafana_data

# Backup dashboard
cp monitoring/grafana/dashboard.json monitoring/grafana/dashboard.backup.json

# Restore dashboard
docker cp monitoring/grafana/dashboard.json grafana:/var/lib/grafana/dashboards/
docker restart grafana
```

### Set Up Alerts

1. **Configure Slack Notification**:
   - Grafana → Configuration → Notification channels
   - Add new channel → Slack
   - Paste Slack webhook URL
   - Test notification

2. **Create Alert Rule**:
   - Edit "Error Rate by Agent" panel
   - Alert tab → Create alert
   - Set threshold: when value > 5
   - Notify: Select Slack channel
   - Save

## Metrics Reference

See [monitoring/README.md](../README.md) for complete metrics documentation.

## Dashboard Lifecycle

**Versioning**: Update `version` field in JSON when changes are made:
```json
"version": 1  // increment on each save
```

**Export Current State**:
- Dashboard settings (gear icon) → **Export** → **Save to File**
- Upload to version control

**Version Control**:
```bash
git add monitoring/grafana/dashboard.json
git commit -m "Update dashboard: add new panel"
```
