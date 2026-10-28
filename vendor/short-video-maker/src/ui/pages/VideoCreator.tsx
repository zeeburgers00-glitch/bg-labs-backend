import React, { useState, useEffect } from "react";
import axios from "axios";
import { useNavigate } from "react-router-dom";
import {
  Box,
  Button,
  TextField,
  Typography,
  Paper,
  Grid,
  FormControl,
  InputLabel,
  Select,
  MenuItem,
  CircularProgress,
  Alert,
  IconButton,
  Divider,
  InputAdornment,
} from "@mui/material";
import AddIcon from "@mui/icons-material/Add";
import DeleteIcon from "@mui/icons-material/Delete";
import {
  SceneInput,
  RenderConfig,
  MusicMoodEnum,
  CaptionPositionEnum,
  VoiceEnum,
  OrientationEnum,
  MusicVolumeEnum,
} from "../../types/shorts";

interface SceneFormData {
  text: string;
  searchTerms: string; // Changed to string
}

const VideoCreator: React.FC = () => {
  const navigate = useNavigate();
  const [scenes, setScenes] = useState<SceneFormData[]>([
    { text: "", searchTerms: "" },
  ]);
  const [config, setConfig] = useState<RenderConfig>({
    paddingBack: 1500,
    music: MusicMoodEnum.chill,
    captionPosition: CaptionPositionEnum.bottom,
    captionBackgroundColor: "blue",
    voice: VoiceEnum.af_heart,
    orientation: OrientationEnum.portrait,
    musicVolume: MusicVolumeEnum.high,
  });

  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [voices, setVoices] = useState<VoiceEnum[]>([]);
  const [musicTags, setMusicTags] = useState<MusicMoodEnum[]>([]);
  const [loadingOptions, setLoadingOptions] = useState(true);

  useEffect(() => {
    const fetchOptions = async () => {
      try {
        const [voicesResponse, musicResponse] = await Promise.all([
          axios.get("/api/voices"),
          axios.get("/api/music-tags"),
        ]);

        setVoices(voicesResponse.data);
        setMusicTags(musicResponse.data);
      } catch (err) {
        console.error("Failed to fetch options:", err);
        setError(
          "Failed to load voices and music options. Please refresh the page.",
        );
      } finally {
        setLoadingOptions(false);
      }
    };

    fetchOptions();
  }, []);

  const handleAddScene = () => {
    setScenes([...scenes, { text: "", searchTerms: "" }]);
  };

  const handleRemoveScene = (index: number) => {
    if (scenes.length > 1) {
      const newScenes = [...scenes];
      newScenes.splice(index, 1);
      setScenes(newScenes);
    }
  };

  const handleSceneChange = (
    index: number,
    field: keyof SceneFormData,
    value: string,
  ) => {
    const newScenes = [...scenes];
    newScenes[index] = { ...newScenes[index], [field]: value };
    setScenes(newScenes);
  };

  const handleConfigChange = (field: keyof RenderConfig, value: any) => {
    setConfig({ ...config, [field]: value });
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    setError(null);

    try {
      // Convert scenes to the expected API format
      const apiScenes: SceneInput[] = scenes.map((scene) => ({
        text: scene.text,
        searchTerms: scene.searchTerms
          .split(",")
          .map((term) => term.trim())
          .filter((term) => term.length > 0),
      }));

      const response = await axios.post("/api/short-video", {
        scenes: apiScenes,
        config,
      });

      navigate(`/video/${response.data.videoId}`);
    } catch (err) {
      setError("Failed to create video. Please try again.");
      console.error(err);
    } finally {
      setLoading(false);
    }
  };

  if (loadingOptions) {
    return (
      <Box
        display="flex"
        justifyContent="center"
        alignItems="center"
        height="80vh"
      >
        <CircularProgress />
      </Box>
    );
  }

  return (
    <Box maxWidth="md" mx="auto" py={4}>
      <Typography variant="h4" component="h1" gutterBottom>
        Create New Video
      </Typography>

      {error && (
        <Alert severity="error" sx={{ mb: 3 }}>
          {error}
        </Alert>
      )}

      <form onSubmit={handleSubmit}>
        <Typography variant="h5" component="h2" gutterBottom>
          Scenes
        </Typography>

        {scenes.map((scene, index) => (
          <Paper key={index} sx={{ p: 3, mb: 3 }}>
            <Box
              display="flex"
              justifyContent="space-between"
              alignItems="center"
              mb={2}
            >
              <Typography variant="h6">Scene {index + 1}</Typography>
              {scenes.length > 1 && (
                <IconButton
                  onClick={() => handleRemoveScene(index)}
                  color="error"
                  size="small"
                >
                  <DeleteIcon />
                </IconButton>
              )}
            </Box>

            <Grid container spacing={3}>
              <Grid item xs={12}>
                <TextField
                  fullWidth
                  label="Text"
                  multiline
                  rows={4}
                  value={scene.text}
                  onChange={(e) =>
                    handleSceneChange(index, "text", e.target.value)
                  }
                  required
                />
              </Grid>

              <Grid item xs={12}>
                <TextField
                  fullWidth
                  label="Search Terms (comma-separated)"
                  value={scene.searchTerms}
                  onChange={(e) =>
                    handleSceneChange(index, "searchTerms", e.target.value)
                  }
                  helperText="Enter keywords for background video, separated by commas"
                  required
                />
              </Grid>
            </Grid>
          </Paper>
        ))}

        <Box display="flex" justifyContent="center" mb={4}>
          <Button
            variant="outlined"
            startIcon={<AddIcon />}
            onClick={handleAddScene}
          >
            Add Scene
          </Button>
        </Box>

        <Divider sx={{ mb: 4 }} />

        <Typography variant="h5" component="h2" gutterBottom>
          Video Configuration
        </Typography>

        <Paper sx={{ p: 3, mb: 3 }}>
          <Grid container spacing={3}>
            <Grid item xs={12} sm={6}>
              <TextField
                fullWidth
                type="number"
                label="End Screen Padding (ms)"
                value={config.paddingBack}
                onChange={(e) =>
                  handleConfigChange("paddingBack", parseInt(e.target.value))
                }
                InputProps={{
                  endAdornment: (
                    <InputAdornment position="end">ms</InputAdornment>
                  ),
                }}
                helperText="Duration to keep playing after narration ends"
                required
              />
            </Grid>

            <Grid item xs={12} sm={6}>
              <FormControl fullWidth>
                <InputLabel>Music Mood</InputLabel>
                <Select
                  value={config.music}
                  onChange={(e) => handleConfigChange("music", e.target.value)}
                  label="Music Mood"
                  required
                >
                  {Object.values(MusicMoodEnum).map((tag) => (
                    <MenuItem key={tag} value={tag}>
                      {tag}
                    </MenuItem>
                  ))}
                </Select>
              </FormControl>
            </Grid>

            <Grid item xs={12} sm={6}>
              <FormControl fullWidth>
                <InputLabel>Caption Position</InputLabel>
                <Select
                  value={config.captionPosition}
                  onChange={(e) =>
                    handleConfigChange("captionPosition", e.target.value)
                  }
                  label="Caption Position"
                  required
                >
                  {Object.values(CaptionPositionEnum).map((position) => (
                    <MenuItem key={position} value={position}>
                      {position}
                    </MenuItem>
                  ))}
                </Select>
              </FormControl>
            </Grid>

            <Grid item xs={12} sm={6}>
              <TextField
                fullWidth
                label="Caption Background Color"
                value={config.captionBackgroundColor}
                onChange={(e) =>
                  handleConfigChange("captionBackgroundColor", e.target.value)
                }
                helperText="Any valid CSS color (name, hex, rgba)"
                required
              />
            </Grid>

            <Grid item xs={12} sm={6}>
              <FormControl fullWidth>
                <InputLabel>Default Voice</InputLabel>
                <Select
                  value={config.voice}
                  onChange={(e) => handleConfigChange("voice", e.target.value)}
                  label="Default Voice"
                  required
                >
                  {Object.values(VoiceEnum).map((voice) => (
                    <MenuItem key={voice} value={voice}>
                      {voice}
                    </MenuItem>
                  ))}
                </Select>
              </FormControl>
            </Grid>

            <Grid item xs={12} sm={6}>
              <FormControl fullWidth>
                <InputLabel>Orientation</InputLabel>
                <Select
                  value={config.orientation}
                  onChange={(e) =>
                    handleConfigChange("orientation", e.target.value)
                  }
                  label="Orientation"
                  required
                >
                  {Object.values(OrientationEnum).map((orientation) => (
                    <MenuItem key={orientation} value={orientation}>
                      {orientation}
                    </MenuItem>
                  ))}
                </Select>
              </FormControl>
            </Grid>

            <Grid item xs={12} sm={6}>
              <FormControl fullWidth>
                <InputLabel>Volume of the background audio</InputLabel>
                <Select
                  value={config.musicVolume}
                  onChange={(e) =>
                    handleConfigChange("musicVolume", e.target.value)
                  }
                  label="Volume of the background audio"
                  required
                >
                  {Object.values(MusicVolumeEnum).map((voice) => (
                    <MenuItem key={voice} value={voice}>
                      {voice}
                    </MenuItem>
                  ))}
                </Select>
              </FormControl>
            </Grid>
          </Grid>
        </Paper>

        <Box display="flex" justifyContent="center">
          <Button
            type="submit"
            variant="contained"
            color="primary"
            size="large"
            disabled={loading}
            sx={{ minWidth: 200 }}
          >
            {loading ? (
              <CircularProgress size={24} color="inherit" />
            ) : (
              "Create Video"
            )}
          </Button>
        </Box>
      </form>
    </Box>
  );
};

export default VideoCreator;
