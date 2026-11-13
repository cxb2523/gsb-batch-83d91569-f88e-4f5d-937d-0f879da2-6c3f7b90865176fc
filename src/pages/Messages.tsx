import { useState, useEffect, useCallback, useMemo, memo, useRef } from 'react';
import { motion, AnimatePresence } from 'motion/react';
import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { z } from 'zod';
import {
  Send,
  MessageSquare,
  Play,
  Square,
  Trash2,
  Download,
  Copy,
  Clock,
  Plus,
  ChevronDown,
  ChevronRight,
  RefreshCw,
  MoreVertical,
  Inbox,
  MailX,
  X,
} from 'lucide-react';

import {cn } from '@/lib/utils';
import { staggerContainer } from '@/lib/animations';

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '../components/ui/card';
import { Button } from '../components/ui/button';
import { Label } from '../components/ui/label';
import { Textarea } from '../components/ui/textarea';
import { Badge } from '../components/ui/badge';
import { JsonViewer } from '../components/ui/json-viewer';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '../components/ui/dropdown-menu';
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from '../components/ui/collapsible';
import { useNats } from '../hooks/useNats';
import { toast } from 'sonner';
import { fetchActiveSubjects } from '../services/nats-service';
import { subjectTracker, type SubjectActivity } from '../services/subject-tracker';
import { getCustomTopics, addCustomTopic, removeCustomTopic } from '../services/custom-topics';
import {
  type CollectionSession,
  type CollectedMessage,
  startSession,
  findActiveSession,
  findLatestSession,
  recordMessage,
  stopSession,
  interruptSession,
  interruptAllSessions,
  clearSessionMessages,
  buildSessionExport,
} from '../services/collection-sessions';
import { TopicSkeleton } from '../components/ui/skeletons';
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle, DialogFooter } from '../components/ui/dialog';
import { Input } from '../components/ui/input';

const publishSchema = z.object({
  data: z.string(),
  headers: z.string().optional(),
});

const subscribeSchema = z.object({
  subject: z.string().min(1, 'Subject is required'),
  queueGroup: z.string().optional(),
});

type PublishFormData = z.infer<typeof publishSchema>;
type SubscribeFormData = z.infer<typeof subscribeSchema>;

// Memoized message item component to prevent unnecessary re-renders
const MessageItem = memo(({ 
  message, 
  isHeaderExpanded, 
  onToggleHeader, 
  onCopyBody,
  onCopyHeaders,
  onCopyAll
}: {
  message: Message;
  isHeaderExpanded: boolean;
  onToggleHeader: (messageId: string) => void;
  onCopyBody: (message: Message) => void;
  onCopyHeaders: (message: Message) => void;
  onCopyAll: (message: Message) => void;
}) => {
  // Memoize expensive computations
  const isJsonData = useMemo(() => {
    try {
      JSON.parse(message.data);
      return true;
    } catch {
      return false;
    }
  }, [message.data]);

  const hasJsonContentType = useMemo(() => {
    return message.headers?.['Content-Type']?.includes('json') || 
           message.headers?.['content-type']?.includes('json');
  }, [message.headers]);

  const handleToggleHeader = useCallback(() => {
    onToggleHeader(message.id);
  }, [onToggleHeader, message.id]);

  return (
    <motion.div
      layout
      initial={{ opacity: 0, x: -20 }}
      animate={{ opacity: 1, x: 0 }}
      exit={{ opacity: 0, x: 20 }}
      transition={{ duration: 0.3 }}
      className="rounded-lg border p-4 space-y-3"
    >
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Badge variant="outline">{message.subject}</Badge>
          <div className="flex items-center gap-1 text-xs text-muted-foreground">
            <Clock className="h-3 w-3" />
            {message.timestamp.toLocaleString()}
          </div>
        </div>
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button
              variant="ghost"
              size="sm"
              title="Copy options"
            >
              <MoreVertical className="h-4 w-4" />
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end">
            <DropdownMenuItem onClick={() => onCopyBody(message)}>
              <Copy className="h-3 w-3 mr-2" />
              Copy Body
            </DropdownMenuItem>
            {message.headers && Object.keys(message.headers).length > 0 && (
              <DropdownMenuItem onClick={() => onCopyHeaders(message)}>
                <Copy className="h-3 w-3 mr-2" />
                Copy Headers
              </DropdownMenuItem>
            )}
            <DropdownMenuItem onClick={() => onCopyAll(message)}>
              <Copy className="h-3 w-3 mr-2" />
              Copy All
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </div>

      {message.headers && Object.keys(message.headers).length > 0 && (
        <div>
          <Button
            variant="ghost"
            size="sm"
            className="w-full justify-between p-0 h-auto font-normal"
            onClick={handleToggleHeader}
          >
            <div className="flex items-center gap-1">
              <motion.div
                animate={{ rotate: isHeaderExpanded ? 90 : 0 }}
                transition={{ duration: 0.2 }}
              >
                <ChevronRight className="h-3 w-3" />
              </motion.div>
              <Label className="text-xs font-medium cursor-pointer">
                Headers ({Object.keys(message.headers).length})
              </Label>
            </div>
          </Button>
          <AnimatePresence>
            {isHeaderExpanded && (
              <motion.div
                initial={{ opacity: 0, height: 0 }}
                animate={{ opacity: 1, height: 'auto' }}
                exit={{ opacity: 0, height: 0 }}
                transition={{ duration: 0.2 }}
                className="overflow-hidden"
              >
                <div className="mt-2 text-sm bg-muted p-2 rounded font-mono space-y-1">
                  {Object.entries(message.headers).map(([key, value]) => (
                    <div key={key} className="flex gap-2">
                      <span className="text-blue-600 dark:text-blue-400">{key}:</span>
                      <span className="text-muted-foreground">{value}</span>
                    </div>
                  ))}
                </div>
              </motion.div>
            )}
          </AnimatePresence>
        </div>
      )}

      {message.data && (
        <div className="space-y-1">
          <Label className="text-xs font-medium">Data:</Label>
          {(isJsonData || hasJsonContentType) ? (
            <JsonViewer data={message.data} defaultExpanded={true} />
          ) : (
            <pre className="text-sm bg-muted p-2 rounded overflow-x-auto font-mono">
              {message.data}
            </pre>
          )}
        </div>
      )}

      {message.replyTo && (
        <div className="space-y-1">
          <Label className="text-xs font-medium">Reply To:</Label>
          <span className="text-sm text-muted-foreground font-mono">{message.replyTo}</span>
        </div>
      )}
    </motion.div>
  );
});

// Messages are stored inside their collection session, not in a global array,
// so what the user sees (and exports) always belongs to one auditable run.
type Message = CollectedMessage;

const SESSION_STATUS_LABEL: Record<CollectionSession['status'], string> = {
  collecting: 'Collecting',
  stopped: 'Stopped',
  interrupted: 'Interrupted',
};

const SESSION_STATUS_VARIANT: Record<CollectionSession['status'], 'default' | 'secondary' | 'destructive'> = {
  collecting: 'default',
  stopped: 'secondary',
  interrupted: 'destructive',
};


const MessagesComponent = function Messages() {
  const { connection, isConnected, config, error: connectionError } = useNats();
  const server = config.server;
  // Collection sessions live only in memory: they describe live subscriptions,
  // so a page reload starts clean and can never resurrect a stale "collecting"
  // state. They are also independent from custom-topic bookmarks.
  const [sessions, setSessions] = useState<CollectionSession[]>([]);
  // Unsubscribe handles are functions, so they live in a ref keyed by session id
  // rather than in serializable state.
  const unsubscribeFns = useRef<Map<string, () => void>>(new Map());
  // Mirror of sessions for event handlers, so subscribe can decide reuse
  // synchronously without side effects inside a state updater.
  const sessionsRef = useRef<CollectionSession[]>(sessions);
  useEffect(() => {
    sessionsRef.current = sessions;
  }, [sessions]);
  const [selectedTopic, setSelectedTopic] = useState<string | null>(null);
  const [topics, setTopics] = useState<string[]>([]);
  const [isLoadingTopics, setIsLoadingTopics] = useState(false);
  const [expandedHeaders, setExpandedHeaders] = useState<Set<string>>(new Set());
  const [hideInboxTopics, setHideInboxTopics] = useState(true);
  const [isAddTopicOpen, setIsAddTopicOpen] = useState(false);
  const [newTopicName, setNewTopicName] = useState('');

  // User-added topics, persisted per server so they survive a page reload.
  // Lazily seeded from localStorage so the list is correct on first paint.
  const [customTopics, setCustomTopics] = useState<string[]>(() => getCustomTopics(server));
  const [loadedTopicsServer, setLoadedTopicsServer] = useState(server);
  const customTopicsRef = useRef<string[]>(customTopics);
  const customTopicsSet = useMemo(() => new Set(customTopics), [customTopics]);

  // Reload persisted custom topics when the active server changes.
  if (server !== loadedTopicsServer) {
    setLoadedTopicsServer(server);
    setCustomTopics(getCustomTopics(server));
  }

  // Mirror the latest custom topics into a ref so polling closures can read them.
  useEffect(() => {
    customTopicsRef.current = customTopics;
  }, [customTopics]);

  const handleAddCustomTopic = useCallback((name: string) => {
    const trimmed = name.trim();
    if (!trimmed) return;

    setCustomTopics(addCustomTopic(server, trimmed));
    setTopics((prev) => [...new Set([...prev, trimmed])].sort());
    setSelectedTopic(trimmed);
    setIsAddTopicOpen(false);
    setNewTopicName('');
  }, [server]);

  const handleRemoveCustomTopic = useCallback((topic: string) => {
    setCustomTopics(removeCustomTopic(server, topic));

    // Keep it if it still has tracked activity (published/received messages);
    // otherwise it was a pure bookmark, so drop it from the list.
    const stillTracked = subjectTracker.getSubjects().some((s) => s.subject === topic);
    if (!stillTracked) {
      setTopics((prev) => prev.filter((t) => t !== topic));
      setSelectedTopic((prev) => (prev === topic ? null : prev));
    }
  }, [server]);

  // State for publish card collapsible behavior
  const [isPublishExpanded, setIsPublishExpanded] = useState(() => {
    // Default to collapsed on smaller screens, expanded on larger screens
    if (typeof window !== 'undefined') {
      return window.innerWidth >= 1024; // lg breakpoint
    }
    return true; // Server-side render default
  });

  // Memoized computations to prevent unnecessary re-renders
  const selectedSession = useMemo(() => {
    if (!selectedTopic) return undefined;
    return findLatestSession(sessions, selectedTopic);
  }, [sessions, selectedTopic]);

  const filteredMessages = useMemo(() => {
    return selectedSession?.messages ?? [];
  }, [selectedSession]);

  // State for subject activities that updates when subjects change
  const [subjectActivities, setSubjectActivities] = useState<Map<string, SubjectActivity>>(new Map());

  // Memoized topic list data with stable references
  const topicListData = useMemo(() => {
    const selectedTopicRef = selectedTopic;
    const sessionsRef = sessions;

    // Filter out _INBOX topics if hideInboxTopics is true
    const filteredTopics = hideInboxTopics
      ? topics.filter(topic => !topic.startsWith('_INBOX.'))
      : topics;

    return filteredTopics.map((topic) => {
      const activity = subjectActivities.get(topic);
      const isSelected = selectedTopicRef === topic;
      const isSubscribed = sessionsRef.some(s => s.subject === topic && s.status === 'collecting');
      const isCustom = customTopicsSet.has(topic);

      return {
        topic,
        activity,
        isSelected,
        isSubscribed,
        isCustom
      };
    });
  }, [topics, subjectActivities, selectedTopic, sessions, hideInboxTopics, customTopicsSet]);
  
  // Memoized topic list component to prevent re-renders
  const TopicListMemoized = useMemo(() => {
    if (isLoadingTopics) {
      return (
        <div className="space-y-2">
          {Array.from({ length: 5 }).map((_, i) => (
            <TopicSkeleton key={i} />
          ))}
        </div>
      );
    }
    
    if (topics.length === 0) {
      return <p className="text-sm text-muted-foreground">No topics found</p>;
    }
    
    return (
      <motion.div
        className="space-y-2"
        variants={staggerContainer}
        initial="hidden"
        animate="visible"
      >
        {topicListData.map(({ topic, activity, isSelected, isSubscribed, isCustom }) => {
          return (
            <div
              key={topic}
              className={`cursor-pointer rounded-lg border p-3 transition-colors ${
                isSelected ? 'bg-primary/10 border-primary' : 'hover:bg-muted/50'
              }`}
              onClick={() => setSelectedTopic(topic)}
            >
              <div className="flex items-center justify-between mb-1">
                <span className="font-mono text-sm truncate">{topic}</span>
                <div className="flex items-center gap-1 flex-shrink-0">
                  <AnimatePresence>
                    {isSubscribed && (
                      <motion.div
                        initial={{ scale: 0, opacity: 0 }}
                        animate={{ scale: 1, opacity: 1 }}
                        exit={{ scale: 0, opacity: 0 }}
                        transition={{ type: 'spring', stiffness: 300, damping: 20 }}
                      >
                        <Badge variant="default" className="text-xs">
                          Subscribed
                        </Badge>
                      </motion.div>
                    )}
                  </AnimatePresence>
                  {isCustom && (
                    <Button
                      variant="ghost"
                      size="icon"
                      className="h-5 w-5 text-muted-foreground hover:text-destructive"
                      onClick={(e) => {
                        e.stopPropagation();
                        handleRemoveCustomTopic(topic);
                      }}
                      title="Remove custom topic"
                    >
                      <X className="h-3 w-3" />
                    </Button>
                  )}
                </div>
              </div>
              {activity && (
                <div className="flex items-center gap-2 text-xs text-muted-foreground">
                  <span>{activity.messageCount} messages</span>
                  <span>•</span>
                  <span>{new Date(activity.lastSeen).toLocaleTimeString()}</span>
                </div>
              )}
            </div>
          );
        })}
      </motion.div>
    );
  }, [topics, topicListData, isLoadingTopics, setSelectedTopic, handleRemoveCustomTopic]);

  const publishForm = useForm<PublishFormData>({
    resolver: zodResolver(publishSchema),
    defaultValues: {
      data: '',
      headers: '',
    },
  });

  const subscribeForm = useForm<SubscribeFormData>({
    resolver: zodResolver(subscribeSchema),
    defaultValues: {
      subject: '',
      queueGroup: '',
    },
  });

  const handlePublish = useCallback(async (data: PublishFormData & { subject: string }) => {
    if (!connection) {
      toast.error('Not connected to NATS server');
      return;
    }

    try {
      let headers: Record<string, string> | undefined;

      // Parse headers if provided
      if (data.headers?.trim()) {
        try {
          headers = JSON.parse(data.headers);
        } catch {
          toast.error('Invalid JSON in headers field');
          return;
        }
      }

      // Use our NatsService publish method with headers
      await connection.publish(data.subject, data.data, headers);

      toast.success(`Message published to ${data.subject}`);
      publishForm.reset();
    } catch (err) {
      console.error('Publish error:', err);
      toast.error('Failed to publish message');
    }
  }, [connection, publishForm]);

  const handleSubscribe = useCallback(async (data: SubscribeFormData) => {

    if (!connection) {
      toast.error('Not connected to NATS server');
      return;
    }

    // One active session per subject: reuse it instead of opening a parallel one.
    const result = startSession(sessionsRef.current, data.subject, data.queueGroup);

    if (result.reused) {
      toast.info(`Already collecting on ${data.subject}`, {
        description: 'The existing collection session is still running.',
      });
      return;
    }

    setSessions(result.sessions);
    sessionsRef.current = result.sessions;
    const sessionId = result.session.id;

    try {
      // Subscribe using our NatsService
      const unsubscribe = await connection.subscribe(data.subject, (msg: { subject: string; data: unknown; headers?: Record<string, string>; timestamp: number; reply?: string }) => {

        const message: Message = {
          id: `msg_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`,
          subject: msg.subject,
          data: typeof msg.data === 'string' ? msg.data : JSON.stringify(msg.data),
          headers: msg.headers, // Headers are now directly available from the message
          timestamp: new Date(msg.timestamp),
          replyTo: msg.reply,
        };

        setSessions(prev => recordMessage(prev, sessionId, message));
      });

      unsubscribeFns.current.set(sessionId, unsubscribe);

      toast.success(`Started collection on ${data.subject}`);
      subscribeForm.reset();
    } catch (err) {
      console.error('Subscribe error:', err);
      const reason = err instanceof Error && err.message ? err.message : 'Failed to subscribe to subject';
      setSessions(prev => interruptSession(prev, sessionId, reason));
      toast.error('Failed to subscribe to subject');
    }
  }, [connection, subscribeForm]);

  const handleUnsubscribe = useCallback((sessionId: string) => {
    const unsubscribe = unsubscribeFns.current.get(sessionId);
    if (unsubscribe) {
      try {
        unsubscribe();
      } catch (err) {
        console.error('Error unsubscribing:', err);
      }
      unsubscribeFns.current.delete(sessionId);
    }
    // The session stays in the list as "stopped" with its count frozen.
    setSessions(prev => stopSession(prev, sessionId));
    toast.success('Collection stopped');
  }, []);

  // When the connection drops, every collecting session must become
  // "interrupted" with a reason — never left showing as collecting. Old
  // sessions are not resumed on reconnect; the user subscribes again.
  const wasConnectedRef = useRef(isConnected);
  useEffect(() => {
    if (wasConnectedRef.current && !isConnected) {
      const reason = connectionError
        ? `Connection lost: ${connectionError}`
        : 'Connection to NATS server lost';
      unsubscribeFns.current.clear();
      const hadCollecting = sessionsRef.current.some(s => s.status === 'collecting');
      setSessions(prev => interruptAllSessions(prev, reason));
      if (hadCollecting) {
        toast.error('Collection sessions interrupted', { description: reason });
      }
    }
    wasConnectedRef.current = isConnected;
  }, [isConnected, connectionError]);


  const toggleHeaderExpansion = useCallback((messageId: string) => {
    setExpandedHeaders(current => {
      const newSet = new Set(current);
      if (newSet.has(messageId)) {
        newSet.delete(messageId);
      } else {
        newSet.add(messageId);
      }
      return newSet;
    });
  }, []);

  const copyMessageBody = useCallback((message: Message) => {
    try {
      const parsedData = JSON.parse(message.data);
      navigator.clipboard.writeText(JSON.stringify(parsedData, null, 2));
    } catch {
      navigator.clipboard.writeText(message.data);
    }
    toast.success('Message body copied to clipboard');
  }, []);

  const copyMessageHeaders = useCallback((message: Message) => {
    if (message.headers && Object.keys(message.headers).length > 0) {
      navigator.clipboard.writeText(JSON.stringify(message.headers, null, 2));
      toast.success('Message headers copied to clipboard');
    } else {
      toast.error('No headers to copy');
    }
  }, []);

  const copyMessageAll = useCallback((message: Message) => {
    const messageJson = {
      subject: message.subject,
      data: (() => {
        try {
          return JSON.parse(message.data);
        } catch {
          return message.data;
        }
      })(),
      headers: message.headers,
      timestamp: message.timestamp.toISOString(),
      ...(message.replyTo && { replyTo: message.replyTo }),
    };
    
    navigator.clipboard.writeText(JSON.stringify(messageJson, null, 2));
    toast.success('Complete message copied to clipboard as JSON');
  }, []);

  // Cache for server topics with timestamp to avoid excessive HTTP calls
  const serverTopicsCache = useRef<{ topics: Set<string>; timestamp: number }>({ topics: new Set(), timestamp: 0 });
  const lastTopicsHash = useRef<string>('');
  
  // Optimized topic comparison using Set-based hashing
  const createTopicsHash = useCallback((topicArray: string[]): string => {
    return topicArray.sort().join('|');
  }, []);

  // Fetch topics from server (HTTP API) with intelligent caching
  const fetchServerTopics = useCallback(async (): Promise<Set<string>> => {
    if (!isConnected) return new Set();
    
    const now = Date.now();
    const cacheAge = now - serverTopicsCache.current.timestamp;
    
    // Use cached server topics if less than 30 seconds old
    if (cacheAge < 30000 && serverTopicsCache.current.topics.size > 0) {
      return serverTopicsCache.current.topics;
    }
    
    try {
      const serverTopics = await fetchActiveSubjects();
      const serverTopicsSet = new Set(serverTopics);
      
      // Update cache
      serverTopicsCache.current = {
        topics: serverTopicsSet,
        timestamp: now
      };
      
      return serverTopicsSet;
    } catch (error) {
      console.warn('Failed to fetch server topics:', error);
      // Return cached topics even if stale, or empty set
      return serverTopicsCache.current.topics;
    }
  }, [isConnected]);

  // Combine and deduplicate topics from both sources
  const fetchTopics = useCallback(async () => {
    if (!isConnected) return;
    
    try {
      setIsLoadingTopics(true);
      
      // Get topics from both sources
      const [serverTopicsSet, subjectTrackerTopics] = await Promise.all([
        fetchServerTopics(),
        Promise.resolve(subjectTracker.getSubjects().map(s => s.subject))
      ]);
      
      // Combine and deduplicate using Set for optimal performance
      const allTopicsSet = new Set([...serverTopicsSet, ...subjectTrackerTopics, ...customTopicsRef.current]);
      const newTopics = Array.from(allTopicsSet).sort();
      
      // Smart comparison using hash to prevent unnecessary re-renders
      const newHash = createTopicsHash(newTopics);
      
      if (newHash !== lastTopicsHash.current) {
        lastTopicsHash.current = newHash;
        setTopics(newTopics);
      }
    } catch (error) {
      console.error('Failed to fetch topics:', error);
    } finally {
      setIsLoadingTopics(false);
    }
  }, [isConnected, fetchServerTopics, createTopicsHash]);

  // Smart polling with different intervals for different sources
  useEffect(() => {
    if (!isConnected) return;
    
    // Initial fetch
    const run = async () => { await fetchTopics(); };
    run();

    // Server topics: Poll every 30 seconds (less frequent to reduce HTTP calls)
    const serverInterval = setInterval(async () => {
      // Only fetch server topics, subject tracker updates will be handled separately
      try {
        const serverTopicsSet = await fetchServerTopics();
        const subjectTrackerTopics = subjectTracker.getSubjects().map(s => s.subject);
        const allTopicsSet = new Set([...serverTopicsSet, ...subjectTrackerTopics, ...customTopicsRef.current]);
        const newTopics = Array.from(allTopicsSet).sort();
        const newHash = createTopicsHash(newTopics);
        
        if (newHash !== lastTopicsHash.current) {
          lastTopicsHash.current = newHash;
          setTopics(newTopics);
        }
      } catch (error) {
        console.error('Failed to update server topics:', error);
      }
    }, 30000);
    
    return () => clearInterval(serverInterval);
  }, [isConnected, fetchServerTopics, createTopicsHash, fetchTopics]);

  // Handle responsive collapse state for publish card
  useEffect(() => {
    const handleResize = () => {
      const isLarge = window.innerWidth >= 1024; // lg breakpoint
      setIsPublishExpanded(isLarge);
    };

    // Set initial state
    handleResize();

    // Add resize listener
    window.addEventListener('resize', handleResize);
    
    return () => window.removeEventListener('resize', handleResize);
  }, []);

  // Update subject activities when they change
  useEffect(() => {
    const updateActivities = () => {
      const subjects = subjectTracker.getSubjects();
      const activitiesMap = new Map(subjects.map(s => [s.subject, s]));
      setSubjectActivities(activitiesMap);
    };
    
    // Initial update
    updateActivities();
    
    // Subscribe to subject tracker changes
    const unsubscribe = subjectTracker.subscribe(updateActivities);
    
    return () => unsubscribe();
  }, []);

  // Subject tracker updates: Debounced and intelligent
  useEffect(() => {
    if (!isConnected) return;
    
    let debounceTimeout: ReturnType<typeof setTimeout>;
    let lastUpdateTime = 0;
    
    const unsubscribe = subjectTracker.subscribe(() => {
      const now = Date.now();
      
      // Clear previous debounce timeout
      clearTimeout(debounceTimeout);
      
      // If it's been less than 2 seconds since last update, debounce more aggressively
      const debounceDelay = (now - lastUpdateTime < 2000) ? 1500 : 500;
      
      debounceTimeout = setTimeout(async () => {
        lastUpdateTime = Date.now();
        
        try {
          // Get fresh subject tracker topics and combine with cached server topics
          const subjectTrackerTopics = subjectTracker.getSubjects().map(s => s.subject);
          const serverTopicsSet = serverTopicsCache.current.topics;
          const allTopicsSet = new Set([...serverTopicsSet, ...subjectTrackerTopics, ...customTopicsRef.current]);
          const newTopics = Array.from(allTopicsSet).sort();
          const newHash = createTopicsHash(newTopics);
          
          if (newHash !== lastTopicsHash.current) {
            lastTopicsHash.current = newHash;
            setTopics(newTopics);
          }
        } catch (error) {
          console.error('Failed to update subject tracker topics:', error);
        }
      }, debounceDelay);
    });
    
    return () => {
      clearTimeout(debounceTimeout);
      unsubscribe();
    };
  }, [isConnected, createTopicsHash]);


  if (!isConnected) {
    return (
      <div className="space-y-6 p-4">
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-3xl font-bold">Messages</h1>
            <p className="text-muted-foreground">
              Connect to NATS server to publish and subscribe to messages
            </p>
          </div>
        </div>

        <div className="flex flex-col items-center justify-center py-12">
          <div className="max-w-md">
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="h-full flex flex-col p-4">
      <div className="flex items-center justify-between mb-6 flex-shrink-0">
        <div>
          <h1 className="text-3xl font-bold">Topics</h1>
          <p className="text-muted-foreground">
            Browse subjects, view messages, and publish to topics
          </p>
        </div>
      </div>

      <div className="flex-1 lg:grid lg:grid-cols-3 gap-6 lg:min-h-0 lg:max-h-[calc(100vh-10rem)]">
        {/* Topics List */}
        <div className="lg:col-span-1 flex flex-col min-h-0">
          <Card className="flex-1 flex flex-col overflow-hidden">
            <CardHeader className="flex-shrink-0">
              <CardTitle className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <MessageSquare className="h-5 w-5" />
                  Topics ({topicListData.length})
                </div>
                <div className="flex gap-1">
                  <Button
                    variant={hideInboxTopics ? "outline" : "default"}
                    size="sm"
                    onClick={() => setHideInboxTopics(!hideInboxTopics)}
                    title={hideInboxTopics ? "Show _INBOX topics" : "Hide _INBOX topics"}
                  >
                    {hideInboxTopics ? <MailX className="h-4 w-4" /> : <Inbox className="h-4 w-4" />}
                  </Button>
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={async () => {
                      try {
                        setIsLoadingTopics(true);
                        // Force fresh fetch from NATS server
                        const freshServerTopics = await fetchActiveSubjects();
                        const subjectTrackerTopics = subjectTracker.getSubjects().map(s => s.subject);

                        // Combine and update
                        const allTopicsSet = new Set([...freshServerTopics, ...subjectTrackerTopics, ...customTopicsRef.current]);
                        const newTopics = Array.from(allTopicsSet).sort();
                        setTopics(newTopics);

                        toast.success('Topics refreshed from NATS server');
                      } catch (error) {
                        console.error('Failed to refresh topics:', error);
                        toast.error('Failed to refresh topics from server');
                      } finally {
                        setIsLoadingTopics(false);
                      }
                    }}
                    disabled={isLoadingTopics}
                    title="Refresh topics from NATS server"
                  >
                    <RefreshCw className={`h-4 w-4 ${isLoadingTopics ? 'animate-spin' : ''}`} />
                  </Button>
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => {
                      setIsAddTopicOpen(true);
                      setNewTopicName('');
                    }}
                    title="Add custom topic"
                  >
                    <Plus className="h-4 w-4" />
                  </Button>
                </div>
              </CardTitle>
            </CardHeader>
            <CardContent className="flex-1 overflow-hidden px-6 relative">
              <div className="h-full overflow-y-auto">
                {TopicListMemoized}
              </div>
              {/* Bottom fade effect */}
              <div className="absolute bottom-0 left-0 right-0 h-8 bg-gradient-to-t from-background to-transparent pointer-events-none" />
            </CardContent>
          </Card>
        </div>

        {/* Topic Details and Actions */}
        <div className="lg:col-span-2 flex flex-col min-h-0">
          {!selectedTopic ? (
            <Card className="flex-1 flex flex-col">
              <CardContent className="flex-1 flex items-center justify-center p-8">
                <div className="text-center space-y-4">
                  <MessageSquare className="h-12 w-12 mx-auto text-muted-foreground" />
                  <div className="space-y-2">
                    <h3 className="text-lg font-semibold text-center">Select a Topic</h3>
                    <p className="text-sm text-muted-foreground text-center max-w-sm mx-auto leading-relaxed">
                      Choose a topic from the list to view messages and publish
                    </p>
                  </div>
                </div>
              </CardContent>
            </Card>
          ) : (
            <div className="flex-1 flex flex-col gap-6 min-h-0 overflow-y-auto">
              {/* Publish to Topic - Collapsible */}
              <Collapsible 
                open={isPublishExpanded} 
                onOpenChange={setIsPublishExpanded}
                className="flex-shrink-0"
              >
                <Card className={cn("overflow-hidden pt-0 gap-2", !isPublishExpanded && 'pb-0')}>
                  <CollapsibleTrigger asChild>
                    <div className="cursor-pointer hover:bg-muted/50 transition-colors p-6 pb-4">
                      <div className="flex items-center justify-between mb-1">
                        <div className="flex items-center gap-2">
                          <Send className="h-5 w-5" />
                          <span className="text-lg font-semibold">Publish to {selectedTopic}</span>
                        </div>
                        <div className="flex items-center gap-2">
                          {!isPublishExpanded && (
                            <Badge variant="secondary" className="text-xs">
                              Click to expand
                            </Badge>
                          )}
                          {isPublishExpanded ? (
                            <ChevronDown className="h-4 w-4 text-muted-foreground" />
                          ) : (
                            <ChevronRight className="h-4 w-4 text-muted-foreground" />
                          )}
                        </div>
                      </div>
                      {!isPublishExpanded && (
                        <p className="text-sm text-muted-foreground">
                          Send messages to this topic
                        </p>
                      )}
                    </div>
                  </CollapsibleTrigger>
                  
                  <CollapsibleContent>
                    <CardContent>
                      <form
                        onSubmit={publishForm.handleSubmit(async (data) => {
                          await handlePublish({ ...data, subject: selectedTopic });
                        })}
                        className="space-y-4"
                        autoComplete="off"
                        data-form-type="other"
                      >
                        <div className="space-y-2">
                          <Label htmlFor="publish-data">Message Data</Label>
                          <Textarea
                            id="publish-data"
                            placeholder="Enter message content..."
                            rows={3}
                            className="max-h-[40vh] overflow-y-auto"
                            {...publishForm.register('data')}
                          />
                        </div>

                        <div className="space-y-2">
                          <Label htmlFor="publish-headers">Headers (JSON, optional)</Label>
                          <Textarea
                            id="publish-headers"
                            placeholder='{"Content-Type": "application/json"}'
                            rows={2}
                            className="max-h-[20vh] overflow-y-auto"
                            {...publishForm.register('headers')}
                          />
                        </div>

                        <Button
                          type="submit"
                          disabled={publishForm.formState.isSubmitting}
                          className="w-full"
                        >
                          <Send className="mr-2 h-4 w-4" />
                          Publish Message
                        </Button>
                      </form>
                    </CardContent>
                  </CollapsibleContent>
                </Card>
              </Collapsible>

              {/* Messages Display - Takes remaining space */}
              <Card className="flex-1 flex flex-col min-h-[18rem] overflow-hidden">
                <CardHeader className="flex-shrink-0 flex flex-row items-center justify-between">
                  <div>
                    <CardTitle className="flex items-center gap-2">
                      <MessageSquare className="h-5 w-5" />
                      Messages for {selectedTopic} ({filteredMessages.length})
                      {selectedSession && (
                        <Badge variant={SESSION_STATUS_VARIANT[selectedSession.status]} className="text-xs">
                          {SESSION_STATUS_LABEL[selectedSession.status]}
                        </Badge>
                      )}
                    </CardTitle>
                    <CardDescription>
                      {selectedSession
                        ? `Session started ${selectedSession.startedAt.toLocaleString()} · ${selectedSession.messageCount} message${selectedSession.messageCount === 1 ? '' : 's'}${selectedSession.lastMessageAt ? ` · last at ${selectedSession.lastMessageAt.toLocaleTimeString()}` : ''}${selectedSession.lastError ? ` · ${selectedSession.lastError}` : ''}`
                        : 'Messages received from this topic'}
                    </CardDescription>
                  </div>
                  <div className="flex items-center gap-2">
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => {
                        if (!selectedSession) return;
                        // Export the session for the selected topic: metadata
                        // (subject, status, count, time range, last error) plus
                        // the message detail. Works for empty and interrupted
                        // sessions too — the status is exported as-is.
                        const exportData = buildSessionExport(selectedSession);
                        const blob = new Blob([JSON.stringify(exportData, null, 2)], {
                          type: 'application/json',
                        });
                        const url = URL.createObjectURL(blob);
                        const a = document.createElement('a');
                        a.href = url;
                        a.download = `nats-session-${selectedTopic}-${new Date().toISOString().split('T')[0]}.json`;
                        document.body.appendChild(a);
                        a.click();
                        document.body.removeChild(a);
                        URL.revokeObjectURL(url);
                        toast.success('Session exported successfully');
                      }}
                      disabled={!selectedSession}
                      title={selectedSession ? 'Export this collection session as JSON' : 'No collection session for this topic yet'}
                    >
                      <Download className="h-4 w-4" />
                    </Button>
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => {
                        if (!selectedSession) return;
                        setSessions(prev => clearSessionMessages(prev, selectedSession.id));
                        toast.success('Messages cleared');
                      }}
                      disabled={!selectedSession || filteredMessages.length === 0}
                    >
                      <Trash2 className="h-4 w-4" />
                    </Button>
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => {
                        const active = selectedTopic ? findActiveSession(sessions, selectedTopic) : undefined;
                        if (active) {
                          handleUnsubscribe(active.id);
                        } else {
                          if (selectedTopic) {
                            handleSubscribe({ subject: selectedTopic, queueGroup: '' });
                          }
                        }
                      }}
                      className="flex items-center justify-center"
                    >
                      {selectedTopic && findActiveSession(sessions, selectedTopic) ? (
                        <Square className="h-4 w-4" />
                      ) : (
                        <Play className="h-4 w-4" />
                      )}
                    </Button>
                  </div>
                </CardHeader>
                <CardContent className="flex-1 overflow-hidden px-6">
                  <div className="h-full overflow-y-auto">
                    {filteredMessages.length === 0 ? (
                      <div className="flex items-center justify-center h-full min-h-0">
                        <div className="text-center space-y-4">
                          <div className="space-y-2">
                            <MessageSquare className="h-12 w-12 mx-auto text-muted-foreground" />
                            <div className="space-y-2">
                              <h3 className="text-lg font-semibold text-center">No messages yet</h3>
                              <p className="text-sm text-muted-foreground text-center max-w-sm mx-auto leading-relaxed">
                                {selectedSession?.status === 'collecting'
                                  ? "Waiting for messages on this topic..."
                                  : selectedSession?.status === 'interrupted'
                                    ? `Collection was interrupted${selectedSession.lastError ? `: ${selectedSession.lastError}` : ''}. Subscribe again to start a new session.`
                                    : "Subscribe to this topic to start receiving messages"}
                              </p>
                            </div>
                          </div>
                          {selectedTopic && findActiveSession(sessions, selectedTopic) ? (
                            <Button
                              variant="outline"
                              onClick={() => {
                                const active = findActiveSession(sessions, selectedTopic);
                                if (active) handleUnsubscribe(active.id);
                              }}
                              className="mx-auto"
                              size="lg"
                            >
                              <Square className="mr-2 h-4 w-4" />
                              Stop Collection
                            </Button>
                          ) : (
                            <Button
                              onClick={() => {
                                if (selectedTopic) {
                                  handleSubscribe({ subject: selectedTopic, queueGroup: '' });
                                }
                              }}
                              className="mx-auto"
                              size="lg"
                            >
                              <Play className="mr-2 h-4 w-4" />
                              Subscribe
                            </Button>
                          )}
                        </div>
                      </div>
                    ) : (
                      <motion.div
                        className="space-y-4"
                        variants={staggerContainer}
                        initial="hidden"
                        animate="visible"
                      >
                        <AnimatePresence mode="popLayout">
                          {filteredMessages.map((message) => (
                            <MessageItem
                              key={message.id}
                              message={message}
                              isHeaderExpanded={expandedHeaders.has(message.id)}
                              onToggleHeader={toggleHeaderExpansion}
                              onCopyBody={copyMessageBody}
                              onCopyHeaders={copyMessageHeaders}
                              onCopyAll={copyMessageAll}
                            />
                          ))}
                        </AnimatePresence>
                      </motion.div>
                    )}
                  </div>
                </CardContent>
              </Card>

              {/* Collection Sessions - auditable subscribe runs, kept after stop */}
              {sessions.length > 0 && (
                <Card className="flex-shrink-0">
                  <CardHeader>
                    <CardTitle className="flex items-center gap-2">
                      <Clock className="h-5 w-5" />
                      Collection Sessions ({sessions.length})
                    </CardTitle>
                    <CardDescription>
                      Each subscribe run is recorded here. Stopped and interrupted sessions are kept for review.
                    </CardDescription>
                  </CardHeader>
                  <CardContent>
                    <div className="space-y-2 max-h-64 overflow-y-auto">
                      {[...sessions].reverse().map((session) => (
                        <div
                          key={session.id}
                          className={`rounded-lg border p-3 space-y-1 cursor-pointer transition-colors ${
                            selectedTopic === session.subject ? 'border-primary bg-primary/5' : 'hover:bg-muted/50'
                          }`}
                          onClick={() => setSelectedTopic(session.subject)}
                        >
                          <div className="flex items-center justify-between gap-2">
                            <span className="font-mono text-sm truncate">{session.subject}</span>
                            <div className="flex items-center gap-2 flex-shrink-0">
                              <span className="text-xs text-muted-foreground">
                                {session.messageCount} message{session.messageCount === 1 ? '' : 's'}
                              </span>
                              <Badge variant={SESSION_STATUS_VARIANT[session.status]} className="text-xs">
                                {SESSION_STATUS_LABEL[session.status]}
                              </Badge>
                              {session.status === 'collecting' && (
                                <Button
                                  variant="ghost"
                                  size="icon"
                                  className="h-5 w-5"
                                  title="Stop collection"
                                  onClick={(e) => {
                                    e.stopPropagation();
                                    handleUnsubscribe(session.id);
                                  }}
                                >
                                  <Square className="h-3 w-3" />
                                </Button>
                              )}
                            </div>
                          </div>
                          <div className="flex items-center gap-2 text-xs text-muted-foreground flex-wrap">
                            <span>started {session.startedAt.toLocaleString()}</span>
                            {session.lastMessageAt && (
                              <>
                                <span>•</span>
                                <span>last message {session.lastMessageAt.toLocaleTimeString()}</span>
                              </>
                            )}
                            {session.endedAt && (
                              <>
                                <span>•</span>
                                <span>ended {session.endedAt.toLocaleTimeString()}</span>
                              </>
                            )}
                          </div>
                          {session.lastError && (
                            <p className="text-xs text-destructive">{session.lastError}</p>
                          )}
                        </div>
                      ))}
                    </div>
                  </CardContent>
                </Card>
              )}
            </div>
          )}
        </div>
      </div>

      {/* Add Topic Modal */}
      <Dialog open={isAddTopicOpen} onOpenChange={setIsAddTopicOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Add Custom Topic</DialogTitle>
            <DialogDescription>
              Enter a topic name to add it to the list.
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor="topic-name">Topic Name</Label>
              <Input
                id="topic-name"
                placeholder="e.g., orders.created"
                value={newTopicName}
                onChange={(e) => setNewTopicName(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter') {
                    handleAddCustomTopic(newTopicName);
                  }
                }}
              />
            </div>
          </div>
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => {
                setIsAddTopicOpen(false);
                setNewTopicName('');
              }}
            >
              Cancel
            </Button>
            <Button
              onClick={() => handleAddCustomTopic(newTopicName)}
              disabled={!newTopicName.trim()}
            >
              Add Topic
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
};

// Memoize the component to prevent unnecessary re-renders
export const Messages = memo(MessagesComponent);