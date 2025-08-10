'use client';

import Link from "next/link";
import { ImageIcon } from "lucide-react";
import { useTranslations } from "next-intl";

export default function Navbar() {
  const t = useTranslations();
  const links = [
    { href: "/", label: t("nav.home", { default: "Home" }) },
    { href: "/chat", label: t("nav.chat") },
    { href: "/patients", label: t("nav.patients") },
    { href: "/dicom", label: t("nav.dicom", { default: "DICOM Viewer" }), icon: ImageIcon },
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