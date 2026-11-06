import Link from "next/link";

export default function NotFound() {
  return (
    <div className="empty" style={{ minHeight: "60vh" }}>
      <b style={{ fontSize: 15 }}>Page not found</b>
      <p>The page you&apos;re looking for doesn&apos;t exist or was moved.</p>
      <Link href="/" className="btn btn-primary">Back to the dashboard</Link>
    </div>
  );
}
