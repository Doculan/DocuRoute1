import React, { useState } from 'react';
import axios from 'axios';

const SVMEvaluation = () => {
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

  const getAssessmentColor = (assessment) => {
    switch (assessment) {
      case 'EXCELLENT': return 'text-green-600';
      case 'GOOD': return 'text-blue-600';
      case 'MODERATE': return 'text-yellow-600';
      default: return 'text-red-600';
    }
  };

  const renderConfusionMatrix = (matrix, labels) => {
    return (
      <div className="overflow-x-auto">
        <table className="min-w-full border border-gray-300">
          <thead>
            <tr>
              <th className="border border-gray-300 px-4 py-2 bg-gray-50">Predicted →</th>
              {labels.map(label => (
                <th key={label} className="border border-gray-300 px-4 py-2 bg-gray-50 font-medium">
                  {label.split(' ')[0]}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {matrix.map((row, i) => (
              <tr key={i}>
                <td className="border border-gray-300 px-4 py-2 bg-gray-50 font-medium">
                  {labels[i].split(' ')[0]}
                </td>
                {row.map((cell, j) => (
                  <td key={j} className={`border border-gray-300 px-4 py-2 text-center font-bold ${
                    i === j ? 'bg-green-100 text-green-800' : cell > 0 ? 'bg-yellow-50 text-yellow-800' : ''
                  }`}>
                    {cell}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    );
  };

  return (
    <div className="p-6">
      <div className="mb-6">
        <h1 className="text-2xl font-bold text-gray-900 mb-2">SVM Model Evaluation</h1>
        <p className="text-gray-600">
          Evaluate the performance of the SVM text categorization model on the expanded dataset.
        </p>
      </div>

      <div className="mb-6">
        <button
          onClick={runEvaluation}
          disabled={loading}
          className="bg-blue-600 hover:bg-blue-700 disabled:bg-blue-400 text-white px-6 py-2 rounded-lg font-medium transition-colors"
        >
          {loading ? 'Running Evaluation...' : 'Run SVM Evaluation'}
        </button>
      </div>

      {error && (
        <div className="mb-6 p-4 bg-red-50 border border-red-200 rounded-lg">
          <p className="text-red-800">{error}</p>
        </div>
      )}

      {evaluationData && (
        <div className="space-y-6">
          {/* Dataset Info */}
          <div className="bg-white p-6 rounded-lg shadow">
            <h2 className="text-xl font-semibold mb-4">Dataset Information</h2>
            <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
              <div className="text-center">
                <div className="text-2xl font-bold text-blue-600">{evaluationData.dataset_info.total_samples}</div>
                <div className="text-sm text-gray-600">Total Samples</div>
              </div>
              <div className="text-center">
                <div className="text-2xl font-bold text-green-600">{evaluationData.dataset_info.categories.length}</div>
                <div className="text-sm text-gray-600">Categories</div>
              </div>
              <div className="text-center">
                <div className="text-2xl font-bold text-purple-600">{evaluationData.dataset_info.training_samples}</div>
                <div className="text-sm text-gray-600">Training</div>
              </div>
              <div className="text-center">
                <div className="text-2xl font-bold text-orange-600">{evaluationData.dataset_info.test_samples}</div>
                <div className="text-sm text-gray-600">Testing</div>
              </div>
            </div>
            <div className="mt-4">
              <p className="text-sm text-gray-600">Categories: {evaluationData.dataset_info.categories.join(', ')}</p>
            </div>
          </div>

          {/* Overall Metrics */}
          <div className="bg-white p-6 rounded-lg shadow">
            <h2 className="text-xl font-semibold mb-4">Overall Performance</h2>
            <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
              <div className="text-center">
                <div className="text-3xl font-bold text-blue-600">{evaluationData.overall_metrics.accuracy}%</div>
                <div className="text-sm text-gray-600">Accuracy</div>
              </div>
              <div className="text-center">
                <div className="text-3xl font-bold text-green-600">{evaluationData.overall_metrics.f1_weighted}%</div>
                <div className="text-sm text-gray-600">F1 Score (Weighted)</div>
              </div>
              <div className="text-center">
                <div className="text-3xl font-bold text-purple-600">{evaluationData.overall_metrics.f1_macro}%</div>
                <div className="text-sm text-gray-600">F1 Score (Macro)</div>
              </div>
            </div>
            <div className="mt-4 text-center">
              <span className={`text-lg font-semibold ${getAssessmentColor(evaluationData.assessment)}`}>
                Assessment: {evaluationData.assessment}
              </span>
            </div>
          </div>

          {/* Per-Class Performance */}
          <div className="bg-white p-6 rounded-lg shadow">
            <h2 className="text-xl font-semibold mb-4">Per-Class F1 Scores</h2>
            <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
              {Object.entries(evaluationData.per_class_f1).map(([category, score]) => (
                <div key={category} className="text-center">
                  <div className="text-2xl font-bold text-indigo-600">{score}%</div>
                  <div className="text-sm text-gray-600 truncate" title={category}>{category}</div>
                </div>
              ))}
            </div>
          </div>

          {/* Cross-Validation */}
          <div className="bg-white p-6 rounded-lg shadow">
            <h2 className="text-xl font-semibold mb-4">Cross-Validation Results</h2>
            <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
              <div className="text-center">
                <div className="text-3xl font-bold text-green-600">{evaluationData.cross_validation.mean_f1}%</div>
                <div className="text-sm text-gray-600">Mean F1 Score</div>
              </div>
              <div className="text-center">
                <div className="text-3xl font-bold text-orange-600">±{evaluationData.cross_validation.std_f1}%</div>
                <div className="text-sm text-gray-600">Standard Deviation</div>
              </div>
              <div className="text-center">
                <div className="text-lg text-gray-600">5-fold CV</div>
                <div className="text-sm text-gray-500">Cross-validation</div>
              </div>
            </div>
            <div className="mt-4">
              <p className="text-sm text-gray-600">
                Individual fold scores: {evaluationData.cross_validation.scores.join('%, ')}%
              </p>
            </div>
          </div>

          {/* Confusion Matrix */}
          <div className="bg-white p-6 rounded-lg shadow">
            <h2 className="text-xl font-semibold mb-4">Confusion Matrix</h2>
            <p className="text-sm text-gray-600 mb-4">
              Shows actual vs predicted classifications. Rows = Actual categories, Columns = Predicted categories.
            </p>
            {renderConfusionMatrix(evaluationData.confusion_matrix.matrix, evaluationData.confusion_matrix.labels)}
          </div>

          {/* Summary */}
          <div className="bg-gray-50 p-6 rounded-lg">
            <h2 className="text-xl font-semibold mb-4">Summary</h2>
            <div className="prose max-w-none">
              <p>
                The SVM model demonstrates <strong className={getAssessmentColor(evaluationData.assessment)}>
                {evaluationData.assessment.toLowerCase()}</strong> performance with{' '}
                <strong>{evaluationData.overall_metrics.accuracy}% accuracy</strong>{' '}
                on a diverse test set of {evaluationData.dataset_info.test_samples} samples.
              </p>
              <p>
                The model excels at categorizing <strong>procedural</strong> and <strong>instructional content</strong>{' '}
                (F1 scores: {evaluationData.per_class_f1.PROCEDURE}% and {evaluationData.per_class_f1['WORKING INSTRUCTION']}%),{' '}
                while <strong>policy classification</strong> shows room for improvement ({evaluationData.per_class_f1.POLICY}% F1).
              </p>
              <p>
                Cross-validation results ({evaluationData.cross_validation.mean_f1}% ± {evaluationData.cross_validation.std_f1}%) {' '}
                confirm reliable performance across different data subsets.
              </p>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

export default SVMEvaluation;