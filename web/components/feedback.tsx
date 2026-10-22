"use client";
export function Loading({ text }: { text: string }) {
  return (
    <div className="loading" role="status">
      <span className="spinner" />
      {text}
    </div>
  );
}
export function ErrorCard({
  message,
  retry,
}: {
  message: string;
  retry: () => void;
}) {
  return (
    <div className="error-card" role="alert">
      <h3>Unable to complete this request</h3>
      <p>{message}</p>
      <button className="button" onClick={retry}>
        Try again
      </button>
    </div>
  );
}
