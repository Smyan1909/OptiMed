'use client';

import React, { useState, useRef, useCallback, useEffect } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { logError } from '@/lib/logger';
import { 
  Upload, 
  ZoomIn, 
  ZoomOut, 
  RotateCw, 
  Info, 
  Maximize2, 
  Trash2, 
  RefreshCw,
  ChevronLeft,
  ChevronRight,
  Play,
  Pause,
  ImageIcon,
  Brain,
  Search,
  Copy,
  Check
} from 'lucide-react';
import { Button } from './ui/button';
import { Badge } from './ui/badge';
import { Slider } from './ui/slider';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogTrigger } from './ui/dialog';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from './ui/select';
import { 
  uploadDICOMImage, 
  listDICOMImages, 
  getDICOMPixelData, 
  deleteDICOMImage,
  analyzeDICOMImage,
  findSimilarDICOMImages,
  fetchPatients,
  fetchPatient
} from '@/lib/api';

interface DICOMImage {
  image_id: string;
  patient_id?: string;
  user_id: string;
  filename: string;
  file_size: number;
  metadata: Record<string, string>;
  dimensions: {
    width: number;
    height: number;
    depth?: number;
    pixel_spacing_x?: number;
    pixel_spacing_y?: number;
    slice_thickness?: number;
  };
  default_window_level: {
    center: number;
    width: number;
  };
  status: string;
  uploaded_at: string;
  processed_at?: string;
  storage_path?: string;
}

interface DICOMPixelData {
  image_id: string;
  image_data_base64: string;
  original_dtype: string;
  photometric_interpretation?: string;
  statistics: Record<string, any>;
}

interface Patient {
  id: string;
  name: string;
  birthDate?: string;
  gender?: string;
  [key: string]: any;
}

interface DICOMViewerProps {
  className?: string;
}

const DICOMAnalysisMarkdownComponents = {
  // Style headings
  h1: ({ children }: any) => <h1 className="text-lg font-bold text-blue-900 mt-4 mb-2">{children}</h1>,
  h2: ({ children }: any) => <h2 className="text-base font-semibold text-blue-900 mt-3 mb-2">{children}</h2>,
  h3: ({ children }: any) => <h3 className="text-sm font-medium text-blue-900 mt-2 mb-1">{children}</h3>,
  
  // Style paragraphs
  p: ({ children }: any) => <p className="text-sm text-blue-900 leading-relaxed mb-2">{children}</p>,
  
  // Style lists - FIXED: Remove list-inside to preserve automatic numbering
  ul: ({ children }: any) => <ul className="list-disc ml-6 space-y-1 mb-2">{children}</ul>,
  
  // Style code blocks
  code: ({ inline, children }: any) => {
    if (inline) {
      return <code className="bg-blue-100 text-blue-800 px-1 py-0.5 rounded text-xs font-mono">{children}</code>;
    }
    return (
      <pre className="bg-blue-100 text-blue-800 p-3 rounded text-xs font-mono overflow-x-auto mb-2">
        <code>{children}</code>
      </pre>
    );
  },
  
  // Style blockquotes
  blockquote: ({ children }: any) => (
    <blockquote className="border-l-4 border-blue-300 pl-3 italic text-blue-800 mb-2">
      {children}
    </blockquote>
  ),
  
  // Style strong/bold text
  strong: ({ children }: any) => <strong className="font-semibold text-blue-900">{children}</strong>,
  
  // Style emphasis/italic text
  em: ({ children }: any) => <em className="italic text-blue-800">{children}</em>,
  
  // Style links
  a: ({ href, children }: any) => (
    <a 
      href={href} 
      target="_blank" 
      rel="noopener noreferrer" 
      className="text-blue-600 hover:text-blue-800 underline"
    >
      {children}
    </a>
  ),
  
  // Style tables
  table: ({ children }: any) => (
    <div className="overflow-x-auto mb-2">
      <table className="min-w-full border-collapse border border-blue-200">{children}</table>
    </div>
  ),
  th: ({ children }: any) => (
    <th className="border border-blue-200 bg-blue-100 px-2 py-1 text-xs font-semibold text-blue-900 text-left">
      {children}
    </th>
  ),
  td: ({ children }: any) => (
    <td className="border border-blue-200 px-2 py-1 text-xs text-blue-900">{children}</td>
  ),
};

export function DICOMViewer({ className }: DICOMViewerProps) {
  const [selectedImage, setSelectedImage] = useState<DICOMImage | null>(null);
  const [uploadedImages, setUploadedImages] = useState<DICOMImage[]>([]);
  const [pixelData, setPixelData] = useState<DICOMPixelData | null>(null);
  const [isUploading, setIsUploading] = useState(false);
  const [isLoading, setIsLoading] = useState(false);
  const [zoom, setZoom] = useState(1);
  const [rotation, setRotation] = useState(0);
  const [windowCenter, setWindowCenter] = useState<number>(0);
  const [windowWidth, setWindowWidth] = useState<number>(0);
  const [isDragging, setIsDragging] = useState(false);
  const [dragStart, setDragStart] = useState({ x: 0, y: 0 });
  const [imagePosition, setImagePosition] = useState({ x: 0, y: 0 });
  
  // Analysis states
  const [analysisQuery, setAnalysisQuery] = useState('');
  const [analysisResult, setAnalysisResult] = useState<string | null>(null);
  const [isAnalyzing, setIsAnalyzing] = useState(false);
  const [similarImages, setSimilarImages] = useState<any[]>([]);
  const [showSimilarImages, setShowSimilarImages] = useState(false);
  
  // Patient context states
  const [selectedPatientId, setSelectedPatientId] = useState('no-patient');
  const [patients, setPatients] = useState<Patient[]>([]);
  const [selectedPatient, setSelectedPatient] = useState<Patient | null>(null);
  const [loadingPatients, setLoadingPatients] = useState(false);
  
  // 3D/Multi-slice support
  const [currentSlice, setCurrentSlice] = useState(0);
  const [isPlaying, setIsPlaying] = useState(false);
  const [playSpeed, setPlaySpeed] = useState(500);
  
  const fileInputRef = useRef<HTMLInputElement>(null);
  const imageRef = useRef<HTMLImageElement>(null);
  const playIntervalRef = useRef<NodeJS.Timeout | null>(null);
  const [copied, setCopied] = useState(false);

  // Load images and patients on component mount
  useEffect(() => {
    loadImages();
    loadPatients();
  }, []);

  // Load patient details when patient ID changes
  useEffect(() => {
    if (selectedPatientId) {
      loadPatientDetails(selectedPatientId);
    } else {
      setSelectedPatient(null);
    }
  }, [selectedPatientId]);

  // Auto-play for 3D volumes
  useEffect(() => {
    if (isPlaying && selectedImage?.dimensions.depth && selectedImage.dimensions.depth > 1) {
      playIntervalRef.current = setInterval(() => {
        setCurrentSlice(prev => {
          const maxSlices = selectedImage.dimensions.depth || 1;
          return (prev + 1) % maxSlices;
        });
      }, playSpeed);
    } else {
      if (playIntervalRef.current) {
        clearInterval(playIntervalRef.current);
        playIntervalRef.current = null;
      }
    }

    return () => {
      if (playIntervalRef.current) {
        clearInterval(playIntervalRef.current);
      }
    };
  }, [isPlaying, playSpeed, selectedImage]);

  const loadImages = async () => {
    try {
      const response = await listDICOMImages();
      setUploadedImages(response.images);
    } catch (error) {
      logError('DICOM Viewer: Failed to load images', error);
      alert('Failed to load images. Please try again.');
    }
  };

  const loadPatients = async () => {
    setLoadingPatients(true);
    try {
      const response = await fetchPatients();
      setPatients(response || []);
    } catch (error) {
      logError('DICOM Viewer: Failed to load patients', error);
      // Don't show error for patients as it might not be critical
    } finally {
      setLoadingPatients(false);
    }
  };

  const loadPatientDetails = async (patientId: string) => {
    try {
      const patient = await fetchPatient(patientId);
      setSelectedPatient(patient);
    } catch (error) {
      logError('DICOM Viewer: Failed to load patient details', error);
      setSelectedPatient(null);
    }
  };

  const handleCopyAnalysis = async () => {
    if (!analysisResult) return;

    try {
      await navigator.clipboard.writeText(analysisResult);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch (error) {
      logError('DICOM Viewer: Failed to copy analysis', error);
    }
  };

  const loadPixelData = async (image: DICOMImage, slice: number = 0) => {
    setIsLoading(true);
    try {
      const data = await getDICOMPixelData(
        image.image_id,
        windowCenter || image.default_window_level.center,
        windowWidth || image.default_window_level.width
      );
      setPixelData(data);
    } catch (error) {
      logError('DICOM Viewer: Failed to load pixel data', error);
      alert('Failed to load image data. Please try again.');
    } finally {
      setIsLoading(false);
    }
  };

  const handleImageSelect = (image: DICOMImage) => {
    setSelectedImage(image);
    setWindowCenter(image.default_window_level.center);
    setWindowWidth(image.default_window_level.width);
    setZoom(1);
    setRotation(0);
    setImagePosition({ x: 0, y: 0 });
    setCurrentSlice(0);
    setIsPlaying(false);
    
    // Auto-select patient if image has patient_id
    if (image.patient_id && image.patient_id !== selectedPatientId) {
      setSelectedPatientId(image.patient_id);
    }
    
    loadPixelData(image, 0);
  };

  const handleAnalyzeImage = async () => {
    if (!selectedImage || !analysisQuery.trim()) return;

    setIsAnalyzing(true);
    try {
      const result = await analyzeDICOMImage(
        selectedImage.image_id,
        analysisQuery,
        selectedPatientId !== 'no-patient' ? selectedPatientId : undefined
      );
      setAnalysisResult(result.analysis);
    } catch (error) {
      logError('DICOM Viewer: Analysis failed', error);
      alert('Failed to analyze image. Please try again.');
    } finally {
      setIsAnalyzing(false);
    }
  };

  const handleFindSimilar = async () => {
    if (!selectedImage) return;

    try {
      const result = await findSimilarDICOMImages(selectedImage.image_id);
      setSimilarImages(result.similar_images);
      setShowSimilarImages(true);
    } catch (error) {
      logError('DICOM Viewer: Similar image search failed', error);
      alert('Failed to find similar images. Please try again.');
    }
  };

  // ... (keep all existing handlers - handleFileSelect, handleDeleteImage, etc.)
  const handleFileSelect = useCallback(async (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    if (!file) return;

    setIsUploading(true);
    try {
      const result = await uploadDICOMImage(file, selectedPatientId !== 'no-patient' ? selectedPatientId : undefined);
      
      await loadImages();
      const newImage = result.image;
      handleImageSelect(newImage);


      alert('DICOM file uploaded successfully!');
    } catch (error) {
      logError('DICOM Viewer: Error uploading DICOM file', error);
      alert('Failed to upload DICOM file. Please try again.');
    } finally {
      setIsUploading(false);
      if (fileInputRef.current) {
        fileInputRef.current.value = '';
      }
    }
  }, [selectedPatientId]);

  const handleDeleteImage = async (imageId: string) => {
    if (!confirm('Are you sure you want to delete this image?')) return;

    try {
      await deleteDICOMImage(imageId);
      setUploadedImages(prev => prev.filter(img => img.image_id !== imageId));
      
      if (selectedImage?.image_id === imageId) {
        setSelectedImage(null);
        setPixelData(null);
      }


      alert('Image deleted successfully');
    } catch (error) {
      logError('DICOM Viewer: Error deleting image', error);
      alert('Failed to delete image. Please try again.');
    }
  };

  const handleWindowingChange = async () => {
    if (!selectedImage) return;
    
    setIsLoading(true);
    try {
      
      const data = await getDICOMPixelData(
        selectedImage.image_id,
        windowCenter,
        windowWidth
      );
      setPixelData(data);
    } catch (error) {
      logError('DICOM Viewer: Failed to apply windowing', error);
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    if (!selectedImage) return;
    
    const timeoutId = setTimeout(() => {
      handleWindowingChange();
    }, 300);

    return () => clearTimeout(timeoutId);
  }, [windowCenter, windowWidth]);

  const handleSliceChange = (newSlice: number) => {
    if (!selectedImage?.dimensions.depth) return;
    
    const maxSlices = selectedImage.dimensions.depth;
    const clampedSlice = Math.max(0, Math.min(newSlice, maxSlices - 1));
    setCurrentSlice(clampedSlice);
  };

  const handleMouseDown = useCallback((event: React.MouseEvent) => {
    setIsDragging(true);
    setDragStart({ x: event.clientX - imagePosition.x, y: event.clientY - imagePosition.y });
  }, [imagePosition]);

  const handleMouseMove = useCallback((event: React.MouseEvent) => {
    if (!isDragging) return;
    
    setImagePosition({
      x: event.clientX - dragStart.x,
      y: event.clientY - dragStart.y,
    });
  }, [isDragging, dragStart]);

  const handleMouseUp = useCallback(() => {
    setIsDragging(false);
  }, []);

  const resetView = () => {
    setZoom(1);
    setRotation(0);
    setImagePosition({ x: 0, y: 0 });
  };

  const handleZoomIn = () => setZoom(prev => Math.min(prev * 1.2, 5));
  const handleZoomOut = () => setZoom(prev => Math.max(prev / 1.2, 0.1));
  const handleRotate = () => setRotation(prev => (prev + 90) % 360);

  const togglePlayback = () => {
    setIsPlaying(prev => !prev);
  };

  const is3D = selectedImage?.dimensions.depth && selectedImage.dimensions.depth > 1;

  return (
    <div className={`p-6 ${className}`}>
      {/* Upload and Image Selection Section */}
      <div className="border-b border-gray-200 pb-6 mb-6">
        <div className="flex flex-col space-y-4">
          {/* Patient Selection */}
          <div className="bg-blue-50 p-4 rounded-lg">
            <label className="block text-sm font-medium text-gray-700 mb-2">
              Patient Context (Optional):
            </label>
            <Select
              value={selectedPatientId}
              onValueChange={setSelectedPatientId}
            >
              <SelectTrigger className="w-full bg-white border-gray-300">
                <SelectValue placeholder="Select a patient for context..." />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="no-patient">No patient selected</SelectItem>
                {patients.map((patient) => (
                  <SelectItem key={patient.id} value={patient.id}>
                    <div className="flex flex-col">
                      <span className="font-medium">{patient.name}</span>
                      <span className="text-xs text-gray-500">
                        {patient.birthDate && `Born: ${patient.birthDate}`}
                        {patient.gender && ` | ${patient.gender}`}
                      </span>
                    </div>
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            {selectedPatient && (
              <div className="mt-2 p-2 bg-white rounded border text-sm">
                <strong>Selected Patient:</strong> {selectedPatient.name}
                {selectedPatient.birthDate && ` (${selectedPatient.birthDate})`}
              </div>
            )}
          </div>

          {/* Upload Section */}
          <div className="flex items-center justify-between">
            <div className="flex items-center space-x-4">
              <input
                ref={fileInputRef}
                type="file"
                accept=".dcm,.dicom"
                onChange={handleFileSelect}
                className="hidden"
              />
              <Button
                onClick={() => fileInputRef.current?.click()}
                disabled={isUploading}
                className="bg-blue-600 hover:bg-blue-700 text-white"
              >
                <Upload className="h-4 w-4 mr-2" />
                {isUploading ? 'Uploading...' : 'Upload DICOM File'}
              </Button>
              
              <Button
                onClick={loadImages}
                variant="outline"
                size="sm"
                className="border-gray-300 text-gray-700 hover:bg-gray-50"
              >
                <RefreshCw className="h-4 w-4 mr-2" />
                Refresh
              </Button>
            </div>

            {uploadedImages.length > 0 && (
              <div className="text-sm text-gray-500">
                {uploadedImages.length} image{uploadedImages.length !== 1 ? 's' : ''} available
              </div>
            )}
          </div>

          {/* Image Selection */}
          {uploadedImages.length > 0 && (
            <div className="bg-gray-50 p-4 rounded-lg">
              <label className="block text-sm font-medium text-gray-700 mb-2">
                Select Image:
              </label>
              <Select
                value={selectedImage?.image_id || ""}
                onValueChange={(imageId) => {
                  const image = uploadedImages.find(img => img.image_id === imageId);
                  if (image) handleImageSelect(image);
                }}
              >
                <SelectTrigger className="w-full bg-white border-gray-300">
                  <SelectValue placeholder="Choose a DICOM image..." />
                </SelectTrigger>
                <SelectContent>
                  {uploadedImages.map((img) => (
                    <SelectItem key={img.image_id} value={img.image_id}>
                      <div className="flex items-center justify-between w-full">
                        <div className="flex flex-col">
                          <span className="font-medium">{img.filename}</span>
                          <span className="text-xs text-gray-500">
                            {img.dimensions.width}×{img.dimensions.height}
                            {img.dimensions.depth && ` (${img.dimensions.depth} slices)`}
                            {img.patient_id && ` | Patient: ${img.patient_id}`}
                          </span>
                        </div>
                        <div className="flex items-center gap-2 ml-4">
                          <Badge 
                            variant={img.status === 'ready' ? 'default' : 'secondary'} 
                            className="text-xs"
                          >
                            {img.status}
                          </Badge>
                          <Button
                            variant="ghost"
                            size="sm"
                            onClick={(e) => {
                              e.stopPropagation();
                              handleDeleteImage(img.image_id);
                            }}
                            className="h-6 w-6 p-0 text-red-500 hover:text-red-700 hover:bg-red-50"
                          >
                            <Trash2 className="h-3 w-3" />
                          </Button>
                        </div>
                      </div>
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          )}
        </div>
      </div>

      {/* Viewer Section */}
      {selectedImage ? (
        <div className="grid grid-cols-1 lg:grid-cols-4 gap-6">
          {/* Image Viewer */}
          <div className="lg:col-span-3">
            {/* ... (keep existing image viewer code) ... */}
            <div className="bg-white border border-gray-200 rounded-lg overflow-hidden">
              {/* Viewer Header */}
              <div className="border-b border-gray-200 p-4">
                <div className="flex items-center justify-between">
                  <div className="flex items-center space-x-3">
                    <div className="h-8 w-8 bg-blue-100 rounded-lg flex items-center justify-center">
                      <ImageIcon className="h-4 w-4 text-blue-600" />
                    </div>
                    <div>
                      <h3 className="text-lg font-medium text-gray-900">
                        {selectedImage.filename}
                      </h3>
                      <div className="flex items-center space-x-2 mt-1">
                        {selectedImage.metadata.Modality && (
                          <Badge variant="outline" className="text-xs">
                            {selectedImage.metadata.Modality}
                          </Badge>
                        )}
                        {is3D && (
                          <Badge variant="outline" className="text-xs bg-green-50 text-green-700 border-green-200">
                            3D Volume ({selectedImage.dimensions.depth} slices)
                          </Badge>
                        )}
                        {selectedPatient && (
                          <Badge variant="outline" className="text-xs bg-blue-50 text-blue-700 border-blue-200">
                            Patient: {selectedPatient.name}
                          </Badge>
                        )}
                      </div>
                    </div>
                  </div>
                  
                  {/* Viewer Controls */}
                  <div className="flex items-center space-x-2">
                    <Button size="sm" variant="outline" onClick={handleZoomIn} className="border-gray-300">
                      <ZoomIn className="h-4 w-4" />
                    </Button>
                    <Button size="sm" variant="outline" onClick={handleZoomOut} className="border-gray-300">
                      <ZoomOut className="h-4 w-4" />
                    </Button>
                    <Button size="sm" variant="outline" onClick={handleRotate} className="border-gray-300">
                      <RotateCw className="h-4 w-4" />
                    </Button>
                    <Button size="sm" variant="outline" onClick={resetView} className="border-gray-300">
                      Reset
                    </Button>
                    <Dialog>
                      <DialogTrigger asChild>
                        <Button size="sm" variant="outline" className="border-gray-300">
                          <Maximize2 className="h-4 w-4" />
                        </Button>
                      </DialogTrigger>
                      <DialogContent className="max-w-6xl max-h-[90vh]">
                        <DialogHeader>
                          <DialogTitle>Full Screen View</DialogTitle>
                        </DialogHeader>
                        <div className="flex justify-center bg-black rounded">
                          {pixelData && (
                            <img
                              src={pixelData.image_data_base64}
                              alt="DICOM Image"
                              className="max-w-full max-h-[70vh] object-contain"
                            />
                          )}
                        </div>
                      </DialogContent>
                    </Dialog>
                  </div>
                </div>

                {/* 3D Navigation Controls - keep existing code */}
                {is3D && (
                  <div className="flex items-center gap-4 pt-4 border-t border-gray-200 mt-4">
                    <div className="flex items-center gap-2">
                      <Button
                        size="sm"
                        variant="outline"
                        onClick={() => handleSliceChange(currentSlice - 1)}
                        disabled={currentSlice === 0}
                        className="border-gray-300"
                      >
                        <ChevronLeft className="h-4 w-4" />
                      </Button>
                      <Button
                        size="sm"
                        variant="outline"
                        onClick={togglePlayback}
                        className="border-gray-300"
                      >
                        {isPlaying ? <Pause className="h-4 w-4" /> : <Play className="h-4 w-4" />}
                      </Button>
                      <Button
                        size="sm"
                        variant="outline"
                        onClick={() => handleSliceChange(currentSlice + 1)}
                        disabled={currentSlice === (selectedImage.dimensions.depth || 1) - 1}
                        className="border-gray-300"
                      >
                        <ChevronRight className="h-4 w-4" />
                      </Button>
                    </div>
                    
                    <div className="flex-1">
                      <div className="flex items-center gap-2">
                        <span className="text-sm text-gray-600">Slice:</span>
                        <Slider
                          value={[currentSlice]}
                          onValueChange={([value]) => handleSliceChange(value)}
                          min={0}
                          max={(selectedImage.dimensions.depth || 1) - 1}
                          step={1}
                          className="flex-1"
                        />
                        <span className="text-sm text-gray-600 w-16">
                          {currentSlice + 1} / {selectedImage.dimensions.depth}
                        </span>
                      </div>
                    </div>
                    
                    <div className="flex items-center gap-2">
                      <span className="text-sm text-gray-600">Speed:</span>
                      <Select value={playSpeed.toString()} onValueChange={(value) => setPlaySpeed(Number(value))}>
                        <SelectTrigger className="w-20 border-gray-300">
                          <SelectValue />
                        </SelectTrigger>
                        <SelectContent>
                          <SelectItem value="100">Fast</SelectItem>
                          <SelectItem value="300">Normal</SelectItem>
                          <SelectItem value="500">Slow</SelectItem>
                          <SelectItem value="1000">Very Slow</SelectItem>
                        </SelectContent>
                      </Select>
                    </div>
                  </div>
                )}
              </div>

              {/* Image Display Area - keep existing code */}
              <div className="p-4">
                <div 
                  className="relative bg-black rounded-lg overflow-hidden flex justify-center items-center border border-gray-300"
                  style={{ minHeight: '500px' }}
                  onMouseDown={handleMouseDown}
                  onMouseMove={handleMouseMove}
                  onMouseUp={handleMouseUp}
                  onMouseLeave={handleMouseUp}
                >
                  {isLoading ? (
                    <div className="text-white flex items-center space-x-2">
                      <div className="animate-spin rounded-full h-6 w-6 border-b-2 border-white"></div>
                      <span>Loading image...</span>
                    </div>
                  ) : pixelData ? (
                    <img
                      ref={imageRef}
                      src={pixelData.image_data_base64}
                      alt="DICOM Image"
                      className="cursor-move select-none"
                      style={{
                        transform: `scale(${zoom}) rotate(${rotation}deg) translate(${imagePosition.x}px, ${imagePosition.y}px)`,
                        transition: isDragging ? 'none' : 'transform 0.1s ease',
                      }}
                      draggable={false}
                    />
                  ) : (
                    <div className="text-gray-400 text-center">
                      <ImageIcon className="h-12 w-12 mx-auto mb-2 opacity-50" />
                      <div>No image data available</div>
                    </div>
                  )}
                  
                  {/* Overlay information */}
                  {pixelData && (
                    <div className="absolute top-4 left-4 text-white text-sm bg-black bg-opacity-75 p-3 rounded-lg">
                      <div><strong>Patient:</strong> {selectedPatient?.name || selectedImage.metadata['Patient Name'] || 'Unknown'}</div>
                      <div><strong>Study:</strong> {selectedImage.metadata['Study Description'] || 'N/A'}</div>
                      {is3D && <div><strong>Slice:</strong> {currentSlice + 1} / {selectedImage.dimensions.depth}</div>}
                    </div>
                  )}
                </div>
                
                {/* View info */}
                <div className="mt-3 text-sm text-gray-600 flex items-center justify-between">
                  <div>
                    Zoom: {Math.round(zoom * 100)}% | Rotation: {rotation}°
                  </div>
                  {pixelData && (
                    <div>
                      Size: {selectedImage.dimensions.width} × {selectedImage.dimensions.height}
                      {is3D && ` × ${selectedImage.dimensions.depth}`}
                    </div>
                  )}
                </div>
              </div>
            </div>
          </div>

          {/* Metadata and Controls Panel */}
          <div className="space-y-6">
            {/* AI Analysis Panel */}
            <div className="bg-white border border-gray-200 rounded-lg p-4">
              <h4 className="font-medium text-gray-900 mb-3 flex items-center">
                <Brain className="h-4 w-4 mr-2 text-blue-600" />
                AI Image Analysis
              </h4>
              <div className="space-y-3">
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-2">
                    Analysis Query
                  </label>
                  <textarea
                    value={analysisQuery}
                    onChange={(e) => setAnalysisQuery(e.target.value)}
                    placeholder="e.g., 'What abnormalities do you see?' or 'Describe the key findings'"
                    className="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
                    rows={3}
                  />
                </div>
                <div className="flex space-x-2">
                  <button
                    onClick={handleAnalyzeImage}
                    disabled={isAnalyzing || !analysisQuery.trim()}
                    className="flex-1 bg-blue-600 hover:bg-blue-700 disabled:bg-gray-400 text-white px-4 py-2 rounded-md transition-colors flex items-center justify-center"
                  >
                    <Brain className="h-4 w-4 mr-2" />
                    {isAnalyzing ? 'Analyzing...' : 'Analyze'}
                  </button>
                  <button
                    onClick={handleFindSimilar}
                    className="flex-1 border border-gray-300 hover:bg-gray-50 text-gray-700 px-4 py-2 rounded-md transition-colors flex items-center justify-center"
                  >
                    <Search className="h-4 w-4 mr-2" />
                    Find Similar
                  </button>
                </div>
                {selectedPatient && selectedPatientId !== 'no-patient' && (
                  <div className="text-xs text-blue-600 bg-blue-50 p-2 rounded">
                    Analysis will include patient context: {selectedPatient.name}
                  </div>
                )}
              </div>
            </div>

            {/* Window/Level Controls - keep existing code */}
            <div className="bg-white border border-gray-200 rounded-lg p-4">
              <h4 className="font-medium text-gray-900 mb-3 flex items-center">
                <Info className="h-4 w-4 mr-2 text-gray-500" />
                Window/Level
              </h4>
              <div className="space-y-4">
                <div>
                  <label className="text-sm text-gray-600 mb-1 block">
                    Center: {windowCenter}
                  </label>
                  <Slider
                    value={[windowCenter]}
                    onValueChange={([value]) => setWindowCenter(value)}
                    min={-1000}
                    max={3000}
                    step={10}
                    className="w-full"
                  />
                </div>
                <div>
                  <label className="text-sm text-gray-600 mb-1 block">
                    Width: {windowWidth}
                  </label>
                  <Slider
                    value={[windowWidth]}
                    onValueChange={([value]) => setWindowWidth(value)}
                    min={1}
                    max={4000}
                    step={10}
                    className="w-full"
                  />
                </div>
              </div>
            </div>

            {/* ... (keep all existing panels - Basic Info, Pixel Statistics, Detailed Metadata) ... */}
            {/* Basic Info */}
            <div className="bg-white border border-gray-200 rounded-lg p-4">
              <h4 className="font-medium text-gray-900 mb-3">Basic Information</h4>
              <div className="space-y-2 text-sm">
                <div className="flex justify-between">
                  <span className="text-gray-600">File:</span>
                  <span className="text-gray-900 font-medium">{selectedImage.filename}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-gray-600">Size:</span>
                  <span className="text-gray-900">{(selectedImage.file_size / 1024 / 1024).toFixed(2)} MB</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-gray-600">Status:</span>
                  <Badge variant={selectedImage.status === 'ready' ? 'default' : 'secondary'}>
                    {selectedImage.status}
                  </Badge>
                </div>
                <div className="flex justify-between">
                  <span className="text-gray-600">Uploaded:</span>
                  <span className="text-gray-900">{new Date(selectedImage.uploaded_at).toLocaleDateString()}</span>
                </div>
                {selectedImage.dimensions.pixel_spacing_x && (
                  <div className="flex justify-between">
                    <span className="text-gray-600">Pixel Spacing:</span>
                    <span className="text-gray-900">
                      {selectedImage.dimensions.pixel_spacing_x.toFixed(2)} × {selectedImage.dimensions.pixel_spacing_y?.toFixed(2)} mm
                    </span>
                  </div>
                )}
                {selectedImage.dimensions.slice_thickness && (
                  <div className="flex justify-between">
                    <span className="text-gray-600">Slice Thickness:</span>
                    <span className="text-gray-900">{selectedImage.dimensions.slice_thickness} mm</span>
                  </div>
                )}
                {is3D && (
                  <div className="flex justify-between">
                    <span className="text-gray-600">Volume Type:</span>
                    <span className="text-gray-900">3D ({selectedImage.dimensions.depth} slices)</span>
                  </div>
                )}
              </div>
            </div>

            {/* Pixel Statistics */}
            {pixelData && (
              <div className="bg-white border border-gray-200 rounded-lg p-4">
                <h4 className="font-medium text-gray-900 mb-3">Pixel Statistics</h4>
                <div className="space-y-2 text-sm">
                  <div className="flex justify-between">
                    <span className="text-gray-600">Min:</span>
                    <span className="text-gray-900">{pixelData.statistics.min?.toFixed(2)}</span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-gray-600">Max:</span>
                    <span className="text-gray-900">{pixelData.statistics.max?.toFixed(2)}</span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-gray-600">Mean:</span>
                    <span className="text-gray-900">{pixelData.statistics.mean?.toFixed(2)}</span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-gray-600">Std:</span>
                    <span className="text-gray-900">{pixelData.statistics.std?.toFixed(2)}</span>
                  </div>
                </div>
              </div>
            )}

            {/* Detailed Metadata */}
            <div className="bg-white border border-gray-200 rounded-lg p-4">
              <h4 className="font-medium text-gray-900 mb-3">DICOM Metadata</h4>
              <div className="max-h-60 overflow-y-auto space-y-2">
                {Object.entries(selectedImage.metadata).map(([key, value]) => (
                  <div key={key} className="text-xs border-b border-gray-100 pb-2 last:border-b-0">
                    <div className="font-medium text-gray-700 mb-1">{key}</div>
                    <div className="text-gray-600 break-words">{value}</div>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </div>
      ) : (
        /* Empty State */
        <div className="text-center py-12">
          <ImageIcon className="h-16 w-16 text-gray-300 mx-auto mb-4" />
          <h3 className="text-lg font-medium text-gray-900 mb-2">No DICOM Image Selected</h3>
          <p className="text-gray-600 mb-6">
            Upload a DICOM file or select an existing image to begin viewing and analysis.
          </p>
          <Button
            onClick={() => fileInputRef.current?.click()}
            className="bg-blue-600 hover:bg-blue-700 text-white"
          >
            <Upload className="h-4 w-4 mr-2" />
            Upload Your First DICOM File
          </Button>
        </div>
      )}

      {/* Enhanced Full-Width Analysis Results Section with Markdown */}
      {analysisResult && (
        <div className="mt-8 bg-white border border-gray-200 rounded-lg shadow-lg">
          <div className="border-b border-gray-200 p-4">
            <div className="flex items-center justify-between">
              <h3 className="text-lg font-medium text-gray-900 flex items-center">
                <Brain className="h-5 w-5 mr-2 text-blue-600" />
                AI Medical Image Analysis
                {selectedPatient && selectedPatientId !== 'no-patient' && (
                  <span className="ml-2 text-sm text-gray-500">
                    for {selectedPatient.name}
                  </span>
                )}
              </h3>
              <div className="flex items-center space-x-2">
                <Button
                  variant="outline"
                  size="sm"
                  onClick={handleCopyAnalysis}
                  className="border-gray-300"
                >
                  {copied ? (
                    <>
                      <Check className="h-4 w-4 mr-1" />
                      Copied
                    </>
                  ) : (
                    <>
                      <Copy className="h-4 w-4 mr-1" />
                      Copy
                    </>
                  )}
                </Button>
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => setAnalysisResult(null)}
                  className="border-red-300 text-red-600 hover:bg-red-50"
                >
                  Clear
                </Button>
              </div>
            </div>
            {selectedImage && (
              <div className="mt-2 flex items-center space-x-2 text-sm text-gray-600">
                <Badge variant="outline" className="text-xs">
                  {selectedImage.metadata.Modality || 'Unknown Modality'}
                </Badge>
                <span>•</span>
                <span>{selectedImage.filename}</span>
                <span>•</span>
                <span>
                  {selectedImage.dimensions.width} × {selectedImage.dimensions.height}
                  {selectedImage.dimensions.depth && ` × ${selectedImage.dimensions.depth}`}
                </span>
              </div>
            )}
          </div>
          
          <div className="p-6">
            <div className="bg-gray-50 border border-gray-200 rounded-lg p-6">
              <div className="dicom-analysis-markdown prose max-w-none">
                <ReactMarkdown
                  components={DICOMAnalysisMarkdownComponents}
                  remarkPlugins={[remarkGfm]}
                >
                  {analysisResult}
                </ReactMarkdown>
              </div>
            </div>
          </div>          
          <div className="border-t border-gray-200 p-4 bg-gray-50">
            <div className="flex justify-between items-center text-sm text-gray-500">
              <span>Analysis completed at {new Date().toLocaleString()}</span>
              <div className="flex items-center space-x-1 text-xs">
                <Brain className="h-3 w-3" />
                <span>AI-powered medical image analysis</span>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Full-Width Similar Images Section */}
      {showSimilarImages && similarImages.length > 0 && (
        <div className="mt-6 bg-white border border-gray-200 rounded-lg shadow-lg">
          <div className="border-b border-gray-200 p-4">
            <h3 className="text-lg font-medium text-gray-900 flex items-center">
              <Search className="h-5 w-5 mr-2 text-green-600" />
              Similar Images Found
              <span className="ml-2 text-sm text-gray-500">
                ({similarImages.length} results)
              </span>
            </h3>
          </div>
          <div className="p-6">
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
              {similarImages.map((similar, index) => (
                <div key={index} className="border border-gray-200 rounded-lg p-4 hover:shadow-md transition-shadow">
                  <div className="flex justify-between items-start mb-3">
                    <div className="font-medium text-base text-gray-900">
                      Similarity: {(similar.similarity * 100).toFixed(1)}%
                    </div>
                    <div className="bg-green-100 text-green-800 text-xs px-2 py-1 rounded-full font-medium">
                      Match
                    </div>
                  </div>
                  <div className="space-y-2 text-sm text-gray-600">
                    <div><strong>Modality:</strong> {similar.metadata.modality || 'N/A'}</div>
                    <div><strong>Body Part:</strong> {similar.metadata.body_part || 'N/A'}</div>
                    <div><strong>Study:</strong> {similar.metadata.study_description || 'N/A'}</div>
                    <div><strong>File:</strong> {similar.metadata.filename}</div>
                    {similar.metadata.patient_id && (
                      <div><strong>Patient:</strong> {similar.metadata.patient_id}</div>
                    )}
                  </div>
                </div>
              ))}
            </div>
          </div>
          <div className="border-t border-gray-200 p-4 bg-gray-50">
            <div className="flex justify-between items-center text-sm text-gray-500">
              <span>Search completed at {new Date().toLocaleString()}</span>
              <button 
                onClick={() => setShowSimilarImages(false)}
                className="text-red-600 hover:text-red-800 font-medium"
              >
                Close Results
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}