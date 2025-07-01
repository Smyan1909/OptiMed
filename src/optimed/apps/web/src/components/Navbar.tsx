import Link from "next/link";
import { ImageIcon } from "lucide-react";

export default function Navbar() {
  const links = [
    { href: "/", label: "Home" },
    { href: "/chat", label: "Chat" },
    { href: "/patients", label: "Patients" },
    { href: "/dicom", label: "DICOM Viewer", icon: ImageIcon },
  ];

  return (
    <nav className="bg-blue-600">
      <div className="container mx-auto px-4 flex items-center h-16">
        <span className="font-bold text-white text-xl mr-8">OptiMed</span>
        <ul className="flex space-x-6">
          {links.map((link) => (
            <li key={link.href}>
              <Link
                href={link.href}
                className="text-white hover:text-gray-200 transition-colors flex items-center gap-2"
              >
                {link.icon && <link.icon className="h-4 w-4" />}
                {link.label}
              </Link>
            </li>
          ))}
        </ul>
      </div>
    </nav>
  );
}