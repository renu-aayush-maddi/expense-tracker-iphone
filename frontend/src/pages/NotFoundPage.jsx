import { Link } from "react-router-dom";

export default function NotFoundPage() {
  return (
    <div className="page page-narrow center">
      <h1>Page not found</h1>
      <p className="muted">The page you're looking for doesn't exist.</p>
      <Link to="/dashboard" className="btn btn-primary">
        Go to dashboard
      </Link>
    </div>
  );
}
