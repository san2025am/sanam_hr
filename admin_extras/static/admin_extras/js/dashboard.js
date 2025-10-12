// Dashboard charts initialization
(function () {
  const dataEl = document.getElementById('dashboard-data');
  if (!dataEl) return;
  let payload = {};
  try {
    payload = JSON.parse(dataEl.textContent || '{}');
  } catch (e) {
    console.warn('Invalid dashboard data');
  }

  function cssVar(name, fallback) {
    const v = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
    return v || fallback || '#c6921c';
  }

  const months = payload.months || [];
  const totals = payload.report_totals || [];
  const reqByStatus = payload.req_by_status || {};
  const attDays = payload.att_days || [];
  const attCounts = payload.att_counts || [];
  const reportsByType = payload.reports_by_type || {};
  const requestsByType = payload.requests_by_type || {};
  const rolesCounts = payload.roles_counts || {};
  const reportsByStatus = payload.reports_by_status || {};
  const violationsByRule = payload.violations_by_rule || {};
  const attendanceBreakdown = payload.attendance_breakdown || {};
  const topLocationsReports = payload.top_locations_reports || {};

  const pieLabels = Object.keys(reqByStatus);
  const pieValues = Object.values(reqByStatus);

  const lineTarget = document.getElementById('reportsChart');
  if (lineTarget && window.Chart) {
    new Chart(lineTarget, {
      type: 'line',
      data: {
        labels: months,
        datasets: [{
          label: 'Reports',
          data: totals,
          fill: false,
          borderColor: cssVar('--brand-gold'),
          tension: 0.1
        }]
      },
      options: {responsive: true, maintainAspectRatio: false}
    });
  }

  const pieTarget = document.getElementById('requestsPie');
  if (pieTarget && window.Chart) {
    new Chart(pieTarget, {
      type: 'doughnut',
      data: {
        labels: pieLabels,
        datasets: [{
          data: pieValues,
          backgroundColor: ['#0d6efd', '#198754', '#dc3545', '#ffc107', '#20c997']
        }]
      },
      options: {responsive: true, maintainAspectRatio: false}
    });
  }

  // Attendance last 7 days
  const attTarget = document.getElementById('attendanceChart');
  if (attTarget && window.Chart) {
    new Chart(attTarget, {
      type: 'line',
      data: {
        labels: attDays,
        datasets: [{
          label: 'Attendance',
          data: attCounts,
          borderColor: 'var(--brand-gold)',
          backgroundColor: 'rgba(198,146,28,0.2)',
          fill: true,
          tension: 0.2
        }]
      },
      options: {responsive: true, maintainAspectRatio: false}
    });
  }

  // Reports by type
  const rbtTarget = document.getElementById('reportsByTypeChart');
  if (rbtTarget && window.Chart) {
    const labels = Object.keys(reportsByType);
    const values = Object.values(reportsByType);
    new Chart(rbtTarget, {
      type: 'bar',
      data: {
        labels,
        datasets: [{
          label: 'Reports by type',
          data: values,
          backgroundColor: 'var(--brand-gold)'
        }]
      },
      options: {responsive: true, maintainAspectRatio: false}
    });
  }

  // Requests by type
  const rqbtTarget = document.getElementById('requestsByTypeChart');
  if (rqbtTarget && window.Chart) {
    const labels = Object.keys(requestsByType);
    const values = Object.values(requestsByType);
    new Chart(rqbtTarget, {
      type: 'doughnut',
      data: {
        labels,
        datasets: [{
          data: values,
          backgroundColor: [cssVar('--brand-gold'), '#198754', '#0dcaf0', '#dc3545', '#6f42c1']
        }]
      },
      options: {responsive: true, maintainAspectRatio: false}
    });
  }

  // Employees by role
  const roleTarget = document.getElementById('rolesChart');
  if (roleTarget && window.Chart) {
    const labels = Object.keys(rolesCounts);
    const values = Object.values(rolesCounts);
    new Chart(roleTarget, {
      type: 'bar',
      data: {
        labels,
        datasets: [{
          label: 'Employees by role',
          data: values,
          backgroundColor: cssVar('--brand-brown', 'rgba(59,36,20,0.6)')
        }]
      },
      options: {responsive: true, maintainAspectRatio: false}
    });
  }

  // Reports by status
  const rbsTarget = document.getElementById('reportsByStatusChart');
  if (rbsTarget && window.Chart) {
    const labels = Object.keys(reportsByStatus);
    const values = Object.values(reportsByStatus);
    new Chart(rbsTarget, {
      type: 'bar',
      data: { labels, datasets: [{ label: 'Reports by status', data: values, backgroundColor: cssVar('--brand-gold') }]},
      options: { responsive: true, maintainAspectRatio: false }
    });
  }

  // Violations by rule (top 10)
  const vbrTarget = document.getElementById('violationsByRuleChart');
  if (vbrTarget && window.Chart) {
    const labels = Object.keys(violationsByRule);
    const values = Object.values(violationsByRule);
    new Chart(vbrTarget, {
      type: 'bar',
      data: { labels, datasets: [{ label: 'Violations by rule', data: values, backgroundColor: cssVar('--accent-cyan') }]},
      options: { responsive: true, maintainAspectRatio: false }
    });
  }

  // Attendance breakdown
  const abpTarget = document.getElementById('attendanceBreakdownPie');
  if (abpTarget && window.Chart) {
    const labels = Object.keys(attendanceBreakdown);
    const values = Object.values(attendanceBreakdown);
    new Chart(abpTarget, {
      type: 'doughnut',
      data: { labels, datasets: [{ data: values, backgroundColor: [cssVar('--accent-teal'), '#6c757d'] }]},
      options: { responsive: true, maintainAspectRatio: false }
    });
  }

  // Top locations by reports
  const tlrTarget = document.getElementById('topLocationsReportsChart');
  if (tlrTarget && window.Chart) {
    const labels = Object.keys(topLocationsReports);
    const values = Object.values(topLocationsReports);
    new Chart(tlrTarget, {
      type: 'bar',
      data: { labels, datasets: [{ label: 'Reports by location', data: values, backgroundColor: cssVar('--accent-amber') }]},
      options: { responsive: true, maintainAspectRatio: false }
    });
  }
  // Re-render on theme toggle to pick up new CSS vars
  document.addEventListener('DOMContentLoaded', function () {
    const tbtn = document.getElementById('theme-toggle');
    if (tbtn) tbtn.addEventListener('click', () => setTimeout(() => location.reload(), 50));
  });
})();
