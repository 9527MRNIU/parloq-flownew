export function EmptyState({
  title,
  description,
}: {
  title: string;
  description: string;
}) {
  return (
    <div className="empty-state">
      <div className="empty-mark" />
      <strong>{title}</strong>
      <span>{description}</span>
    </div>
  );
}
export function Spinner() {
  return <span className="spinner" role="status" aria-label="加载中" />;
}
