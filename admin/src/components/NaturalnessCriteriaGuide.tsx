import type { NaturalnessCriteria } from "../lib/naturalnessCriteria";

export function NaturalnessCriteriaGuide({
  criteria,
  pending,
  error,
}: {
  criteria?: NaturalnessCriteria;
  pending?: boolean;
  error?: string | null;
}) {
  return (
    <details className="nat-criteria-guide">
      <summary>자연스러움 채점 기준 (1~5 앵커)</summary>
      {pending && <p className="muted">기준을 불러오는 중…</p>}
      {error && <p className="form-error">{error}</p>}
      {criteria && (
        <>
          <p className="muted">
            {criteria.version}
            {criteria.scale.note ? ` · ${criteria.scale.note}` : ""}
          </p>
          {criteria.items.map((item) => (
            <div key={item.id} className="nat-criteria-item">
              <strong>
                {item.label} · {item.id}
              </strong>
              <p>{item.text}</p>
              <table>
                <thead>
                  <tr>
                    <th>점수</th>
                    <th>관찰 앵커</th>
                  </tr>
                </thead>
                <tbody>
                  {(["1", "2", "3", "4", "5"] as const).map((score) => (
                    <tr key={score}>
                      <td>{score}</td>
                      <td>{item.likert[score]}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ))}
        </>
      )}
    </details>
  );
}
