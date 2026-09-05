import type { Metadata } from 'next';
import './globals.css';
export const metadata: Metadata = {
  title: 'Build League · Blade Lab',
  description: 'Live voltage and team trials for the East Bay Makers Club generator challenge.',
};
export default function RootLayout({children}: Readonly<{children: React.ReactNode}>) {
  return <html lang="en" className="dark"><body>{children}</body></html>;
}
