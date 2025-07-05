'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { useUser } from '@/contexts/UserContext';
import { UserProfile } from '@/components/UserProfile';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Stethoscope, Users, MessageSquare, Settings, Images} from 'lucide-react';
import { cn } from '@/lib/utils';

const navigation = [
  { name: 'Patients', href: '/patients', icon: Users },
  { name: 'Chat', href: '/chat', icon: MessageSquare },
  { name: 'DICOM Viewer', href: '/dicom', icon: Images },
  { name: 'Admin', href: '/admin', icon: Settings, adminOnly: true },
];

export function Header() {
  const pathname = usePathname();
  const { user } = useUser();

  return (
    <header className="bg-white border-b border-gray-200 shadow-sm">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
        <div className="flex justify-between items-center h-16">
          <div className="flex items-center space-x-4">
            <Link href="/patients" className="flex items-center space-x-2">
              <div className="h-8 w-8 bg-blue-600 rounded-lg flex items-center justify-center">
                <Stethoscope className="h-5 w-5 text-white" />
              </div>
              <span className="text-xl font-bold text-gray-900">CLARA</span>
            </Link>
            
            {user && (
              <Badge variant="outline" className="text-xs">
                {user.role.charAt(0).toUpperCase() + user.role.slice(1)}
              </Badge>
            )}
          </div>

          <nav className="hidden md:flex space-x-1">
            {navigation.map((item) => {
              if (item.adminOnly && user?.role !== 'admin') return null;
              
              const isActive = pathname === item.href;
              const Icon = item.icon;
              
              return (
                <Link key={item.name} href={item.href}>
                  <Button 
                    variant={isActive ? "default" : "ghost"} 
                    size="sm"
                    className={cn(
                      "flex items-center space-x-2",
                      isActive ? "bg-blue-600 text-white" : "text-gray-600 hover:text-gray-900"
                    )}
                  >
                    <Icon className="h-4 w-4" />
                    <span>{item.name}</span>
                  </Button>
                </Link>
              );
            })}
          </nav>

          <div className="flex items-center space-x-4">
            {user && (
              <div className="hidden sm:flex flex-col items-end text-sm">
                <span className="font-medium text-gray-900">{user.display_name}</span>
                <span className="text-xs text-gray-500">{user.department}</span>
              </div>
            )}
            <UserProfile />
          </div>
        </div>
      </div>
    </header>
  );
}