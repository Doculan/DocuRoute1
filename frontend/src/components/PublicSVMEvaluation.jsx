import { useState } from 'react';
import axios from 'axios';

const ASSESSMENT_TONE = {
  EXCELLENT: 'badge-success',
  GOOD: 'badge-info',
  MODERATE: 'badge-warning',
};

function ConfusionMatrix({ matrix, labels }) {
  const max = Math.max(...matrix.flat(), 1);

  return (
    <div className="table-scroll">
      <table className="table matrix">
        <thead>
          <tr>
            <th>Actual \ Predicted</th>
            {labels.map((label) => (
              <th key={label} title={label}>{label.split(' ')[0]}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {matrix.map((row, i) => (
            <tr key={labels[i]}>
              <td className="table-strong" title={labels[i]}>{labels[i].split(' ')[0]}</td>
              {row.map((cell, j) => (
                <td
                  key={labels[j]}
                  className={`matrix-cell${i === j ? ' is-diagonal' : cell > 0 ? ' is-miss' : ''}`}
                  style={{ '--heat': cell / max }}
                >
                  {cell}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function MetricBar({ label, value }) {
  return (
    <div className="metric">
      <div className="metric-head">
        <span className="metric-label" title={label}>{label}</span>
        <span className="metric-value">{value}%</span>
      </div>
      {/* Below 60% the class is not reliable enough to trust unreviewed. */}
      <div className="meter">
        <span
          className={`meter-fill${value < 60 ? " is-low" : ""}`}
          style={{ width: `${value}%` }}
        />
      </div>
    </div>
  );
}

export default function PublicSVMEvaluation() {
  const [evaluationData, setEvaluationData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  const runEvaluation = async () => {
    setLoading(true);
    setError(null);
    try {
      const response = await axios.get('/api/evaluate/svm/');
      setEvaluationData(response.data);
    } catch (err) {
      setError(err.response?.data?.error || 'Failed to run evaluation');
    } finally {
      setLoading(false);
    }
  };

  const d = evaluationData;

  return (
    <div className="public-page">
      <header className="public-hero">
        <div className="public-hero-inner">
          <span className="badge badge-info badge-dot badge-live" style={{ marginBottom: "1rem" }}>
            Model diagnostics
          </span>
          <h1 className="public-hero-title">SVM Model Evaluation</h1>
          <p className="public-hero-sub">
            Text categorization performance analysis for the controlled document management system.
          </p>
          <button className="btn btn-lg" onClick={runEvaluation} disabled={loading}
            style={{ marginTop: "1.75rem", background: "#fff", color: "var(--brand-800)" }}>
            {loading ? <><span className="spinner" /> Running evaluation…</> : 'Run evaluation'}
          </button>
        </div>
      </header>

      <main className="public-body">
        {error && <div className="alert alert-danger">{error}</div>}

        {!d && !loading && !error && (
          <div className="empty-state">
            <div className="empty-icon">📊</div>
            <p className="empty-title">Ready when you are</p>
            <p className="empty-text">
              Run an evaluation to see accuracy, F1 scores, cross-validation results and the confusion matrix.
            </p>
          </div>
        )}

        {d && (
          <div className="col stagger" style={{ gap: "1.25rem" }}>
            <section className="card card-pad">
              <div className="row" style={{ justifyContent: "space-between", marginBottom: "1.1rem" }}>
                <h3 className="section-title">Overall performance</h3>
                <span className={`badge ${ASSESSMENT_TONE[d.assessment] || 'badge-danger'}`}>
                  {d.assessment}
                </span>
              </div>
              <div className="stat-grid" style={{ marginBottom: 0 }}>
                <div className="stat-card">
                  <span className="stat-value">{d.overall_metrics.accuracy}%</span>
                  <span className="stat-label">Accuracy</span>
                </div>
                <div className="stat-card is-success">
                  <span className="stat-value">{d.overall_metrics.f1_weighted}%</span>
                  <span className="stat-label">F1 score (weighted)</span>
                </div>
                <div className="stat-card">
                  <span className="stat-value">{d.overall_metrics.f1_macro}%</span>
                  <span className="stat-label">F1 score (macro)</span>
                </div>
              </div>
            </section>

            <section className="card card-pad">
              <h3 className="section-title" style={{ marginBottom: "1.1rem" }}>Dataset</h3>
              <div className="stat-grid" style={{ marginBottom: "1rem" }}>
                <div className="stat-card">
                  <span className="stat-value">{d.dataset_info.total_samples}</span>
                  <span className="stat-label">Total samples</span>
                </div>
                <div className="stat-card">
                  <span className="stat-value">{d.dataset_info.categories.length}</span>
                  <span className="stat-label">Categories</span>
                </div>
                <div className="stat-card">
                  <span className="stat-value">{d.dataset_info.training_samples}</span>
                  <span className="stat-label">Training</span>
                </div>
                <div className="stat-card is-warning">
                  <span className="stat-value">{d.dataset_info.test_samples}</span>
                  <span className="stat-label">Testing</span>
                </div>
              </div>
              <div className="row-wrap" style={{ gap: "0.4rem" }}>
                {d.dataset_info.categories.map((c) => (
                  <span key={c} className="badge badge-neutral">{c}</span>
                ))}
              </div>
            </section>

            <section className="card card-pad">
              <h3 className="section-title" style={{ marginBottom: "1.1rem" }}>Per-class F1 scores</h3>
              <div className="col" style={{ gap: "0.9rem" }}>
                {Object.entries(d.per_class_f1).map(([category, score]) => (
                  <MetricBar key={category} label={category} value={score} />
                ))}
              </div>
            </section>

            <section className="card card-pad">
              <h3 className="section-title" style={{ marginBottom: "1.1rem" }}>Cross-validation (5-fold)</h3>
              <div className="stat-grid" style={{ marginBottom: "1rem" }}>
                <div className="stat-card is-success">
                  <span className="stat-value">{d.cross_validation.mean_f1}%</span>
                  <span className="stat-label">Mean F1 score</span>
                </div>
                <div className="stat-card is-warning">
                  <span className="stat-value">±{d.cross_validation.std_f1}%</span>
                  <span className="stat-label">Standard deviation</span>
                </div>
              </div>
              <p className="muted text-sm">Fold scores: {d.cross_validation.scores.join('%, ')}%</p>
            </section>

            <section className="card card-pad">
              <h3 className="section-title">Confusion matrix</h3>
              <p className="muted text-sm" style={{ margin: "0.35rem 0 1.1rem" }}>
                Rows are actual categories, columns are predicted. The diagonal is correct classifications.
              </p>
              <ConfusionMatrix matrix={d.confusion_matrix.matrix} labels={d.confusion_matrix.labels} />
            </section>
          </div>
        )}
      </main>
    </div>
  );
}
