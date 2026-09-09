import "./globals.css";
export const metadata = {
  title: "Arkbyte • Research terminal",
  description: "Private multi-agent equity research",
  robots: { index: false, follow: false },
};
export default function Layout({ children }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
